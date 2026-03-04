"""密码哈希工具（纯 stdlib，无第三方依赖）"""

import hashlib


def hash_text(text: str) -> str:
    """SHA-256 哈希"""
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def verify_text(text: str, hashed: str) -> bool:
    """比对哈希"""
    return hash_text(text) == hashed
