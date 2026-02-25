"""小秘密题目目录"""

from typing import List, Optional

from pydantic import BaseModel


class SecretQuestion(BaseModel):
    """一道秘密问题"""

    id: str
    question: str
    gender: str  # "male" | "female" | "all"
    category: str


# ── 题目库 ──────────────────────────────────────────────

QUESTIONS: List[SecretQuestion] = [
    # ── 通用 ──
    SecretQuestion(id="all_01", question="你小时候最害怕的一件事是什么？", gender="all", category="童年"),
    SecretQuestion(id="all_02", question="你做过最疯狂的一件事是什么？", gender="all", category="经历"),
    SecretQuestion(id="all_03", question="你最珍藏的一个物品是什么？", gender="all", category="物品"),
    SecretQuestion(id="all_04", question="你最想对十年后的自己说什么？", gender="all", category="心愿"),
    SecretQuestion(id="all_05", question="你有什么只有自己知道的小习惯？", gender="all", category="习惯"),
    SecretQuestion(id="all_06", question="你最难忘的一顿饭是什么？", gender="all", category="美食"),

    # ── 男性专属 ──
    SecretQuestion(id="male_01", question="你心目中最帅的一个瞬间是什么？", gender="male", category="自我"),
    SecretQuestion(id="male_02", question="你偷偷练过什么技能但没人知道？", gender="male", category="技能"),
    SecretQuestion(id="male_03", question="你最想拥有的超能力是什么？", gender="male", category="幻想"),
    SecretQuestion(id="male_04", question="你最不愿意被别人知道的爱好是什么？", gender="male", category="爱好"),

    # ── 女性专属 ──
    SecretQuestion(id="female_01", question="你藏在心底最甜的一件小事是什么？", gender="female", category="情感"),
    SecretQuestion(id="female_02", question="你最喜欢在什么时候偷偷笑？", gender="female", category="情绪"),
    SecretQuestion(id="female_03", question="你有什么别人猜不到的隐藏技能？", gender="female", category="技能"),
    SecretQuestion(id="female_04", question="你最想去的一个地方和原因？", gender="female", category="旅行"),
]


def get_questions(gender: Optional[str] = None) -> List[SecretQuestion]:
    """获取题目列表（可按性别筛选）"""
    if gender is None:
        return QUESTIONS
    return [q for q in QUESTIONS if q.gender in ("all", gender)]
