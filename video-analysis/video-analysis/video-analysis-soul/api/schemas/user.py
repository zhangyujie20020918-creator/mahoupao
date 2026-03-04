"""User Schema"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class UserCreate(BaseModel):
    """创建用户请求"""

    name: str


class UserResponse(BaseModel):
    """用户信息响应"""

    id: str
    name: str
    created_at: datetime
    last_active: datetime


class UserListResponse(BaseModel):
    """用户列表响应"""

    users: List[UserResponse] = []
