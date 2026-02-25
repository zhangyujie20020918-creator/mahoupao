"""自定义异常类"""


class SoulBaseError(Exception):
    """Soul 基础异常"""

    def __init__(self, message: str = "", detail: str = ""):
        self.message = message
        self.detail = detail
        super().__init__(message)


class PersonaNotFoundError(SoulBaseError):
    """Persona 未找到"""
    pass


class PersonaLoadError(SoulBaseError):
    """Persona 加载失败"""
    pass


class UserNotFoundError(SoulBaseError):
    """用户未找到"""
    pass


class UserAlreadyExistsError(SoulBaseError):
    """用户已存在"""
    pass


class LLMError(SoulBaseError):
    """LLM 调用失败"""
    pass


class LLMTimeoutError(LLMError):
    """LLM 调用超时"""
    pass


class RetrievalError(SoulBaseError):
    """检索失败"""
    pass


class ChromaDBError(RetrievalError):
    """ChromaDB 操作失败"""
    pass


class MemoryError(SoulBaseError):
    """记忆操作失败"""
    pass


class DataCorruptionError(SoulBaseError):
    """数据损坏"""

    def __init__(self, message: str = "", file_path: str = ""):
        self.file_path = file_path
        super().__init__(message)


class SessionError(SoulBaseError):
    """会话错误"""
    pass


class ConfigError(SoulBaseError):
    """配置错误"""
    pass
