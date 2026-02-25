"""用户数据模型"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from common.utils.datetime import now


class UserProfile(BaseModel):
    """用户档案"""

    id: str
    name: str
    created_at: datetime = Field(default_factory=now)
    last_active: datetime = Field(default_factory=now)
