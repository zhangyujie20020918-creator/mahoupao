"""
API 数据模型 (Pydantic Schemas)
"""

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, List

from pydantic import BaseModel, Field, HttpUrl


class PlatformEnum(str, Enum):
    """支持的平台"""
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    DOUYIN = "douyin"
    BILIBILI = "bilibili"
    REDNOTE = "rednote"


class QualityEnum(str, Enum):
    """画质选项"""
    BEST = "best"
    P1080 = "1080p"
    P720 = "720p"
    P480 = "480p"


# ============ 请求模型 ============

class DownloadRequest(BaseModel):
    """下载请求"""
    url: str = Field(..., description="视频URL", examples=["https://www.youtube.com/watch?v=dQw4w9WgXcQ"])
    platform: Optional[PlatformEnum] = Field(None, description="平台（可选，自动检测）")
    quality: QualityEnum = Field(QualityEnum.BEST, description="画质")
    audio_only: bool = Field(False, description="仅下载音频")
    output_dir: Optional[str] = Field(None, description="自定义下载目录（绝对路径）")
    folder_name: Optional[str] = Field(None, description="在下载目录下创建的子文件夹名称")


class VideoInfoRequest(BaseModel):
    """获取视频信息请求"""
    url: str = Field(..., description="视频URL")


# ============ 响应模型 ============

class VideoInfoResponse(BaseModel):
    """视频信息响应"""
    url: str
    platform: str
    video_id: str
    title: str
    author: Optional[str] = None
    duration: Optional[float] = None  # 部分平台返回浮点数
    thumbnail: Optional[str] = None
    description: Optional[str] = None
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    available_qualities: List[str] = []


class DownloadResponse(BaseModel):
    """下载响应"""
    success: bool
    message: str
    video_info: Optional[VideoInfoResponse] = None
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    file_size_human: Optional[str] = None
    elapsed_time: Optional[float] = None
    subtitle_path: Optional[str] = None  # 字幕文件路径


class DownloadProgressResponse(BaseModel):
    """下载进度响应"""
    task_id: str
    status: str  # pending, downloading, merging, completed, failed
    progress: float  # 0-100
    speed: Optional[str] = None
    eta: Optional[int] = None
    error: Optional[str] = None


class PlatformInfo(BaseModel):
    """平台信息"""
    name: str
    value: str
    domains: List[str]


class PlatformsResponse(BaseModel):
    """支持的平台列表响应"""
    platforms: List[PlatformInfo]


class BatchDownloadItemResponse(BaseModel):
    """批量下载单项结果"""
    title: str
    success: bool
    file_path: Optional[str] = None
    file_size_human: Optional[str] = None
    error: Optional[str] = None


class BatchDownloadResponse(BaseModel):
    """批量下载响应"""
    success: bool
    message: str
    total: int
    succeeded: int
    failed: int
    results: List[BatchDownloadItemResponse]
    elapsed_time: Optional[float] = None


class ErrorResponse(BaseModel):
    """错误响应"""
    success: bool = False
    error: str
    detail: Optional[str] = None
