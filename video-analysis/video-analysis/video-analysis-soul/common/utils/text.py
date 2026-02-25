"""文本处理工具"""

import hashlib
import re


def get_collection_name(persona_name: str) -> str:
    """
    生成 ChromaDB collection 名称（与 maker 完全一致）

    必须与 video-analysis-maker/storage/chroma_manager.py
    中的 _sanitize_collection_name() 逻辑完全相同。
    """
    name_hash = hashlib.md5(persona_name.encode("utf-8")).hexdigest()[:8]

    # 只保留字母数字和允许的字符
    sanitized = re.sub(r"[^a-zA-Z0-9._-]", "", persona_name)

    if not sanitized:
        sanitized = f"soul_{name_hash}"
    else:
        if not sanitized[0].isalnum():
            sanitized = f"b{sanitized}"
        if not sanitized[-1].isalnum():
            sanitized = f"{sanitized}0"
        sanitized = f"{sanitized}_{name_hash}"

    # 长度校验 (3-512)
    if len(sanitized) < 3:
        sanitized = f"col_{sanitized}"
    elif len(sanitized) > 512:
        sanitized = sanitized[:512]

    return sanitized


def truncate_text(text: str, max_length: int = 500) -> str:
    """截断文本"""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."
