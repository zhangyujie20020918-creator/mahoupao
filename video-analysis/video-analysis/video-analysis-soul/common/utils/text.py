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


# ── 句子断点检测 ────────────────────────────────────────
#
# 设计原则：
#   1. 编号列表 (1. 2. 3.) 是最高优先级 — 每个编号项独立一个气泡
#   2. 段落换行 (\n\n) 次之
#   3. 中文句号 (。) 是常规断句标点，门槛适中
#   4. 感叹号/问号 (！？!?) 门槛很高 — 避免切碎强调句式
#      例如 "AI是主线！AI是主线！AI是主线！" 不应被拆开
#   5. 逗号 (，) 仅在超长文本中兜底
#
_PERIOD_CN = set("。")
_EXCL_CN = set("！？")
_STRONG_EN = set(".!?")
_MEDIUM = set("；…")
_CLAUSE = set("，、：")

# 不同断点类型的最低文本长度（字符数）
_PERIOD_MIN = 20     # 。句号：至少 20 字符才断
_EXCL_MIN = 80       # ！？感叹/问号：至少 80 字符（保护强调句式）
_MEDIUM_MIN = 30     # ；… 分号/省略号
_CLAUSE_MIN = 80     # ，、逗号兜底

# 编号列表正则：\n 后跟 数字 + (. 、 ) ）)
_LIST_PATTERN = re.compile(r"\n(?=\s*\d+[.、)）]\s*)")


def find_sentence_boundary(text: str, min_length: int = 0) -> int:
    """
    在文本中寻找第一个有效的句子分割位置（前向扫描 + 分层阈值）。

    断点优先级与阈值:
    1. 编号列表 (\\n + 数字.)  — 结构性断点，min_length 即可
    2. 段落换行 (\\n\\n)       — 结构性断点，min_length 即可
    3. 句号 (。 / 英文.)      — 常规断句，>= 20 字符
    4. 分号/省略号 (；…)      — >= 30 字符
    5. 感叹/问号 (！？ / !?)  — >= 80 字符（避免拆碎强调）
    6. 单独换行 (\\n)          — >= 20 字符
    7. 逗号兜底 (，、：)      — >= 80 字符

    返回断点字符的索引（含该字符），未找到返回 -1。
    """
    # ── 结构性断点（最高优先级）──────────────────────

    # 段落换行
    idx = text.find("\n\n")
    if idx >= 0 and idx >= min_length:
        return idx + 1  # 返回第二个 \n 的位置

    # 编号列表项：\n 后跟 "1." "2、" 等
    m = _LIST_PATTERN.search(text)
    if m and m.start() >= min_length:
        return m.start()  # 返回 \n 的位置

    # ── 前向扫描（分层阈值）──────────────────────────
    period_min = max(min_length, _PERIOD_MIN)
    excl_min = max(min_length, _EXCL_MIN)
    medium_min = max(min_length, _MEDIUM_MIN)
    clause_min = max(min_length, _CLAUSE_MIN)

    best_clause = -1

    for i, ch in enumerate(text):
        pos_len = i + 1  # 从开头到当前字符（含）的长度

        # 中文句号 — 最自然的断句点
        if ch in _PERIOD_CN and pos_len >= period_min:
            return i

        # 英文句末（. ! ?）
        if ch in _STRONG_EN:
            if i + 1 >= len(text) or text[i + 1] in (" ", "\n", "\r"):
                # 排除数字小数点和编号 (如 "3.14", "1.")
                if ch == "." and i > 0 and text[i - 1].isdigit():
                    continue
                # 英文 . 用句号阈值，英文 ! ? 用感叹号阈值
                threshold = period_min if ch == "." else excl_min
                if pos_len >= threshold:
                    return i

        # 中文感叹号/问号 — 高阈值，保护强调句式
        if ch in _EXCL_CN and pos_len >= excl_min:
            return i

        # 中断点：分号、省略号
        if ch in _MEDIUM and pos_len >= medium_min:
            return i

        # 单独换行（列表项间、段落内换行）
        if ch == "\n" and pos_len >= period_min:
            # 确认后面不是 \n（\n\n 在上方处理了）
            if i + 1 < len(text) and text[i + 1] != "\n":
                return i

        # 弱断点：逗号等，记录第一个满足长度的位置作为兜底
        if ch in _CLAUSE and pos_len >= clause_min and best_clause < 0:
            best_clause = i

    return best_clause
