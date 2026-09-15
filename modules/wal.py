"""Write-Ahead Log - JSONL预写日志保证数据安全."""
import json
import glob
import os
import tempfile
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict

log = logging.getLogger("baize")

# 2026-08-12 修复：WAL 文件被多个写入方并发追加（/add 请求线程 + periodic_flush
# 后台线程）时，open("a") buffered 写入交错会导致部分行丢失——append 落盘了但
# 紧跟的 mark_complete 被覆盖，产生"内容已入库但账未销"的孤儿 pending。
# 全局锁串行化所有文件写入（append/mark_complete/cleanup 全流程）。
_wal_lock = threading.Lock()

class WALEngine:
    """JSONL write-ahead log for crash recovery."""

    # 2026-08-20 WAL 治理：默认 2MB 自动轮转 + 7 天归档保留
    DEFAULT_MAX_BYTES = 2 * 1024 * 1024

    def __init__(self, wal_path: str, retention_days: int = 7, max_bytes: int = DEFAULT_MAX_BYTES):
        self.wal_path = wal_path
        self.retention_days = retention_days
        self.max_bytes = max_bytes
        os.makedirs(os.path.dirname(wal_path), exist_ok=True)

    # -------------------- rotation helpers --------------------

    def _archive_path(self) -> str:
        """Generate timestamped archive path next to the live WAL."""
        base = Path(self.wal_path)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        return str(base.with_suffix(f".jsonl.{ts}"))

    def append(self, operation: str, data: Dict) -> None:
        """Append an operation to the WAL before executing it."""
        entry = {
            "ts": datetime.now().isoformat(),
            "op": operation,
            "data": data,
            "status": "pending",
        }
        try:
            with _wal_lock:
                self._maybe_rotate_locked()
                with open(self.wal_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            log.error(f"WAL append failed: {e}")
            raise

    def mark_complete(self, operation: str, data: Dict) -> None:
        """Mark an operation as complete in the WAL."""
        entry = {
            "ts": datetime.now().isoformat(),
            "op": operation,
            "data": data,
            "status": "complete",
        }
        try:
            with _wal_lock:
                self._maybe_rotate_locked()
                with open(self.wal_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            log.error(f"WAL mark_complete failed: {e}")
            raise

    def _maybe_rotate_locked(self) -> None:
        """Rotate WAL when it exceeds max_bytes. Must be called inside _wal_lock."""
        if not os.path.exists(self.wal_path):
            return
        try:
            size = os.path.getsize(self.wal_path)
        except OSError:
            return
        if size < self.max_bytes:
            return
        archive = self._archive_path()
        os.replace(self.wal_path, archive)
        log.info(f"WAL rotated: {self.wal_path} ({size} bytes) -> {archive}")

    def _remove_expired_archives(self) -> int:
        """Delete archive files older than retention_days. Idempotent."""
        cutoff = datetime.now() - timedelta(days=self.retention_days)
        removed = 0
        base = Path(self.wal_path)
        pattern = str(base) + ".*"
        for path_str in glob.glob(pattern):
            # 跳过 live 文件本身
            if path_str == self.wal_path:
                continue
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(path_str))
                if mtime < cutoff:
                    os.remove(path_str)
                    removed += 1
                    log.info(f"WAL archive expired: {path_str}")
            except OSError as e:
                log.warning(f"WAL archive cleanup skipped {path_str}: {e}")
        return removed

    # -------------------- replay / cleanup --------------------

    def replay(self) -> list:
        """Replay pending operations on startup.

        D1: 先收集全部 complete 键，再过滤 pending。原实现顺序扫描时，
        pending 记录出现在同键 complete 之前会被误判为待重放，导致幂等重放失效。
        2026-08-20: 轮转后的归档文件（wal_path.*）也纳入扫描，按时间升序
        与 live 文件一同汇总 complete keys，避免高负载轮转后崩溃丢失归档 pending。
        """
        # 按文件名时间戳升序排列归档文件（*.jsonl.<ts>），live 文件最后汇总
        archived = sorted(glob.glob(self.wal_path + ".*"))
        paths = archived + [self.wal_path] if os.path.exists(self.wal_path) else archived
        if not paths:
            return []

        completed = set()
        entries = []

        for path in paths:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            log.warning(f"WAL replay: skipping corrupted line: {line[:80]}")
                            continue
                        key = json.dumps(entry["data"], sort_keys=True)
                        if entry["status"] == "complete":
                            completed.add(key)
                        elif entry["status"] == "pending":
                            entries.append((key, entry))
            except Exception as e:
                log.warning(f"WAL replay read failed ({path}): {e}")

        return [entry for key, entry in entries if key not in completed]

    def cleanup(self) -> int:
        """WAL 治理入口：保留 7 天内记录 + 删除过期归档。

        注意：此函数只清理 live WAL 和 archives；真正的 pending 重放/处理
        由服务启动时的 replay() 完成。若 pending 未 complete 且未过期，会
        被保留（不会误删“真 pending”）。
        """
        if not os.path.exists(self.wal_path):
            self._remove_expired_archives()
            return 0

        cutoff = datetime.now() - timedelta(days=self.retention_days)
        kept = []
        removed = 0

        try:
            with _wal_lock:
                with open(self.wal_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            log.warning(f"WAL cleanup: skipping corrupted line: {line[:80]}")
                            kept.append(line)
                            continue
                        ts = datetime.fromisoformat(entry["ts"])
                        if ts >= cutoff:
                            kept.append(line)
                        else:
                            removed += 1

                dirpath = os.path.dirname(self.wal_path) or "."
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=dirpath, delete=False,
                ) as tmp:
                    tmp_path = tmp.name
                    for line in kept:
                        tmp.write(line + "\n")

                os.replace(tmp_path, self.wal_path)
            archives_removed = self._remove_expired_archives()
        except Exception as e:
            log.error(f"WAL cleanup failed: {e}")
            if "tmp_path" in locals():
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            archives_removed = 0
            raise

        return removed + archives_removed
