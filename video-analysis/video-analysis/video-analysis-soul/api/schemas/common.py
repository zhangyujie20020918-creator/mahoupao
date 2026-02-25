"""通用 Schema"""

from typing import Any, Optional

from pydantic import BaseModel


class BaseResponse(BaseModel):
    """基础响应"""

    success: bool = True
    message: str = ""
    data: Optional[Any] = None


class ErrorResponse(BaseModel):
    """错误响应"""

    success: bool = False
    error: str = ""
    detail: str = ""
