"""Cross-Encoder Reranker - Improve retrieval precision with cross-attention scoring."""
import json
import hashlib
import time
import logging
import threading
import urllib.request
from collections import OrderedDict
from typing import List, Dict, Optional

log = logging.getLogger("baize")

import os as _os
# Voyage 主用（200M 免费）+ bge-m3 兜底（SiliconFlow 免费）
VOYAGE_RERANK_URL = "https://api.voyageai.com/v1/rerank"
VOYAGE_RERANK_MODEL = "rerank-2.5-lite"
BGE_RERANK_URL = "https://api.siliconflow.cn/v1/rerank"
BGE_RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
# 兼容旧常量
RERANK_API_URL = VOYAGE_RERANK_URL
RERANK_MODEL = VOYAGE_RERANK_MODEL
VOYAGE_KEY_PATH = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), ".voyage_key")
EMBED_KEY_PATH_FB = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), ".embed_key")


class Reranker:
    """Voyage rerank-2.5-lite 主用 + bge-reranker-v2-m3 兜底（LRU cache）。"""

    def __init__(self, api_key: str = "", api_url: str = RERANK_API_URL, model: str = RERANK_MODEL,
                 cache_size: int = 100, cache_ttl_sec: int = 300,
                 fallback_api_key: str = "", fallback_api_url: str = BGE_RERANK_URL, fallback_model: str = BGE_RERANK_MODEL):
        # Voyage 主用 key：优先显式 api_key，否则读 .voyage_key / BAIZE_VOYAGE_KEY
        _vk = (api_key or "").strip()
        if not _vk:
            _vk = _os.environ.get("BAIZE_VOYAGE_KEY", "").strip()
            if not _vk and _os.path.exists(VOYAGE_KEY_PATH):
                try:
                    with open(VOYAGE_KEY_PATH) as f: _vk = f.read().strip()
                except Exception: pass
        self.api_key = _vk
        self.api_url = api_url or VOYAGE_RERANK_URL
        self.model = model or VOYAGE_RERANK_MODEL
        # bge 兜底
        _fk = (fallback_api_key or "").strip() or _os.environ.get("BAIZE_EMBED_KEY", "").strip()
        if not _fk and _os.path.exists(EMBED_KEY_PATH_FB):
            try:
                with open(EMBED_KEY_PATH_FB) as f: _fk = f.read().strip()
            except Exception: pass
        self.fallback_api_key = _fk
        self.fallback_api_url = fallback_api_url
        self.fallback_model = fallback_model
        if _vk or _fk:
            log.info(f"Reranker keys: voyage={'set' if _vk else 'missing'} bge={'set' if _fk else 'missing'} (Voyage:{self.model} primary, bge:{self.fallback_model} fallback)")
        self.cache_size = cache_size
        self.cache_ttl_sec = cache_ttl_sec
        # LRU cache: {key: (expire_at, result)}
        self._cache: OrderedDict[str, tuple] = OrderedDict()
        self._cache_lock = threading.Lock()

    def _cache_key(self, query: str, documents: List[Dict]) -> str:
        """Generate a stable cache key from query + document IDs (or content hashes)."""
        doc_ids = []
        for doc in documents:
            # Use id if available, otherwise hash content
            doc_id = doc.get("id")
            if doc_id is not None:
                doc_ids.append(str(doc_id))
            else:
                doc_ids.append(hashlib.sha256(doc.get("content", "").encode("utf-8")).hexdigest()[:16])
        raw = query + "||" + "|".join(doc_ids)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _cache_get(self, key: str) -> Optional[List[Dict]]:
        """Return cached result if valid, else None."""
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            expire_at, result = entry
            if time.time() >= expire_at:
                del self._cache[key]
                return None
            self._cache.move_to_end(key)  # mark as recently used
            return result

    def _cache_put(self, key: str, result: List[Dict]):
        """Insert result into cache, evicting LRU entries if full."""
        with self._cache_lock:
            now = time.time()
            expire_at = now + self.cache_ttl_sec
            self._cache[key] = (expire_at, result)
            self._cache.move_to_end(key)
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)

    def _call_rerank(self, api_url: str, api_key: str, model: str, query: str, doc_texts: List[str], top_k: int):
        """单次 rerank 调用，Voyage 响应格式为 {data:[{relevance_score,index}]}，bge 兼容 results。"""
        payload = {"model": model, "query": query, "documents": doc_texts, "top_k": top_k, "return_documents": False}
        data = json.dumps(payload).encode()
        req = urllib.request.Request(api_url, data=data, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read())
        # 兼容两种返回：Voyage {data:[...]} / SiliconFlow {results:[...]}
        items = result.get("data") if "data" in result else result.get("results", [])
        # Voyage 有时 data 里是 {"relevance_score":..,"index":..}，与 bge 同形，直接复用
        return items

    def rerank(self, query: str, documents: List[Dict], top_k: int = 5) -> List[Dict]:
        """Voyage 主用 + bge 兜底 rerank（LRU cache）。"""
        if not documents:
            return []
        if not self.api_key and not self.fallback_api_key:
            log.warning("Reranker: no API key, skipping rerank")
            return documents[:top_k]
        cache_key = self._cache_key(query, documents)
        cached = self._cache_get(cache_key)
        if cached is not None:
            log.info(f"Reranker cache HIT (key={cache_key[:12]}...), returning {len(cached)} docs")
            return cached[:top_k]
        doc_texts = [doc.get("content", "") for doc in documents]
        k = min(top_k, len(documents))
        # 1) Voyage 主用
        if self.api_key:
            try:
                items = self._call_rerank(self.api_url, self.api_key, self.model, query, doc_texts, k)
                reranked = []
                for item in items:
                    idx = item.get("index", 0)
                    score = item.get("relevance_score", 0)
                    if 0 <= idx < len(documents):
                        doc = documents[idx].copy()
                        doc["rerank_score"] = score
                        reranked.append(doc)
                if reranked:
                    log.info(f"Reranker(Voyage {self.model}): reranked {len(documents)} docs, top {len(reranked)}")
                    self._cache_put(cache_key, reranked)
                    return reranked
            except Exception as e:
                log.warning(f"Reranker Voyage failed: {e}, fallback to bge")
        # 2) bge-m3 兜底
        if self.fallback_api_key:
            try:
                items = self._call_rerank(self.fallback_api_url, self.fallback_api_key, self.fallback_model, query, doc_texts, k)
                reranked = []
                for item in items:
                    idx = item.get("index", 0)
                    score = item.get("relevance_score", 0)
                    if 0 <= idx < len(documents):
                        doc = documents[idx].copy()
                        doc["rerank_score"] = score
                        reranked.append(doc)
                if reranked:
                    log.info(f"Reranker(bge {self.fallback_model}): reranked {len(documents)} docs, top {len(reranked)}")
                    self._cache_put(cache_key, reranked)
                    return reranked
            except Exception as e:
                log.warning(f"Reranker bge fallback failed: {e}")
        log.warning("Reranker all backends failed, returning original order")
        return documents[:top_k]
