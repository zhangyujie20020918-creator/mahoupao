"""用户数据模型"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from common.utils.datetime import now


class SecretAnswer(BaseModel):
    """用户保存的小秘密答案"""

    question_id: str
    answer_hash: str


class UserProfile(BaseModel):
    """用户档案"""

    id: str
    name: str
    gender: Optional[str] = None
    passphrase_hash: Optional[str] = None
    secrets: List[SecretAnswer] = []
    is_anonymous: bool = True
    is_registered: bool = False
    created_at: datetime = Field(default_factory=now)
    last_active: datetime = Field(default_factory=now)
