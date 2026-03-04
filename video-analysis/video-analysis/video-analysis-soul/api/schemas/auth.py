"""Auth Schema"""

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


# ── 请求 ──────────────────────────────────────────────


class RegisterRequest(BaseModel):
    """完整注册"""

    name: str
    gender: str  # "male" | "female"
    passphrase: str
    secrets: List[Dict] = Field(
        ..., min_length=1, description="[{question_id, answer}]"
    )


class UpgradeRequest(BaseModel):
    """匿名升级为注册用户"""

    user_id: str
    name: str
    gender: str = "unknown"
    passphrase: str = ""
    secrets: List[Dict] = Field(default=[])


class VerifyPassphraseRequest(BaseModel):
    """口令验证"""

    user_id: str
    passphrase: str


class VerifySecretRequest(BaseModel):
    """小秘密验证"""

    user_id: str
    question_id: str
    answer: str


# ── 响应 ──────────────────────────────────────────────


class AuthUserResponse(BaseModel):
    """用户信息（含注册状态）"""

    id: str
    name: str
    gender: Optional[str] = None
    is_anonymous: bool
    is_registered: bool
    has_passphrase: bool
    secret_count: int
    created_at: datetime
    last_active: datetime


class ChallengeResponse(BaseModel):
    """秘密挑战题"""

    question_id: str
    question: str
    category: str


class SecretQuestionItem(BaseModel):
    """题目目录条目"""

    id: str
    question: str
    gender: str
    category: str


class SecretCatalogResponse(BaseModel):
    """题目目录"""

    questions: List[SecretQuestionItem]


class VerifyResult(BaseModel):
    """验证结果"""

    verified: bool
    user_id: Optional[str] = None
    message: str = ""
