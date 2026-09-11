"""int8 向量量化公共函数（B7: 从 hybrid_recall 抽取，供检索与迁移脚本共用）。"""
import numpy as np


def quantize_int8(vector) -> bytes:
    """float32 向量 → int8 量化 bytes（L2 归一化 × 127）。

    接受 list/array（已解码的向量）或 bytes（float32 二进制 blob，避免
    tolist 往返）。余弦相似度在量化后仍保留（符号+幅度 7bit 精度），存储 4x 压缩。
    """
    if isinstance(vector, (bytes, bytearray, memoryview)):
        arr = np.frombuffer(vector, dtype=np.float32)
    else:
        arr = np.array(vector, dtype=np.float32)
    norm = np.linalg.norm(arr)
    if norm > 1e-9:
        arr = arr / norm * 127.0
    return np.clip(np.round(arr), -127, 127).astype(np.int8).tobytes()
