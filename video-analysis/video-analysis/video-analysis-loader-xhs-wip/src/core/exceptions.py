"""
自定义异常定义
"""


class DownloaderError(Exception):
    """下载器基础异常"""

    def __init__(self, message: str, url: str = None):
        self.message = message
        self.url = url
        super().__init__(self.message)


class UnsupportedPlatformError(DownloaderError):
    """不支持的平台"""

    def __init__(self, url: str):
        super().__init__(f"不支持的平台或URL: {url}", url)


class VideoNotFoundError(DownloaderError):
    """视频不存在"""

    def __init__(self, url: str, reason: str = None):
        message = f"视频不存在: {url}"
        if reason:
            message += f" ({reason})"
        super().__init__(message, url)


class DownloadFailedError(DownloaderError):
    """下载失败"""

    def __init__(self, url: str, reason: str):
        super().__init__(f"下载失败: {reason}", url)


class NetworkError(DownloaderError):
    """网络错误"""

    def __init__(self, url: str, reason: str = None):
        message = f"网络错误: {url}"
        if reason:
            message += f" ({reason})"
        super().__init__(message, url)


class AuthenticationError(DownloaderError):
    """认证错误（需要登录或Cookie）"""

    def __init__(self, platform: str, reason: str = None):
        message = f"{platform} 需要登录认证"
        if reason:
            message += f": {reason}"
        super().__init__(message)


class RateLimitError(DownloaderError):
    """请求频率限制"""

    def __init__(self, url: str, retry_after: int = None):
        message = "请求过于频繁，请稍后重试"
        if retry_after:
            message += f" (建议等待 {retry_after} 秒)"
        super().__init__(message, url)
        self.retry_after = retry_after
