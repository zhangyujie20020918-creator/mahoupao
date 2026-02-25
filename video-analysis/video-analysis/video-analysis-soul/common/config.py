"""配置管理"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# 加载 .env
load_dotenv()

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent


class PersonaKnowledgeConfig(BaseModel):
    top_k: int = 10
    rerank_top_k: int = 3
    include_context: bool = True
    context_window: int = 2


class PersonaConfig(BaseModel):
    maker_output_path: str = "../video-analysis-maker/output"
    default_persona: Optional[str] = None
    knowledge_retrieval: PersonaKnowledgeConfig = PersonaKnowledgeConfig()


class PreviewConfig(BaseModel):
    retention: str = "permanent"
    summary_trigger_messages: int = 10


class DetailedHistoryConfig(BaseModel):
    retention_days: int = 14
    archive_enabled: bool = True


class LongTermMemoryConfig(BaseModel):
    enabled: bool = True
    retention: str = "permanent"
    max_facts: int = 200


class MemoryConfig(BaseModel):
    preview: PreviewConfig = PreviewConfig()
    detailed_history: DetailedHistoryConfig = DetailedHistoryConfig()
    long_term: LongTermMemoryConfig = LongTermMemoryConfig()


class CacheConfig(BaseModel):
    idle_timeout_seconds: int = 600
    max_sessions: int = 50
    max_messages_per_session: int = 100
    max_memory_mb: int = 512
    cleanup_interval_seconds: int = 60


class LLMConfig(BaseModel):
    default_model: str = "gemini-2.5-flash"
    analysis_model: str = "gemini-2.5-flash"
    summary_model: str = "gemini-2.5-flash"
    available_models: List[str] = [
        "gemini-2.5-flash",
        "gemini-2.5-pro",
    ]
    timeout_seconds: int = 30
    max_retries: int = 2


class IntentConfig(BaseModel):
    enabled: bool = True
    confidence_threshold: float = 0.7


class EmotionConfig(BaseModel):
    enabled: bool = True
    general_triggers: List[List[str]] = [
        ["开心", "高兴", "兴奋", "激动"],
        ["难过", "伤心", "失落", "沮丧"],
        ["焦虑", "担心", "紧张", "害怕"],
        ["生气", "愤怒", "烦躁", "不满"],
    ]
    response_style: Dict[str, str] = {
        "positive": "warm",
        "negative": "empathetic",
        "anxious": "reassuring",
    }


class InfoExtractionConfig(BaseModel):
    enabled: bool = True
    extract_types: List[str] = [
        "person_name",
        "location",
        "event",
        "preference",
        "relationship",
    ]


class AnalysisConfig(BaseModel):
    intent: IntentConfig = IntentConfig()
    emotion: EmotionConfig = EmotionConfig()
    info_extraction: InfoExtractionConfig = InfoExtractionConfig()


class StreamingConfig(BaseModel):
    chunk_size: int = 10
    heartbeat_interval_ms: int = 15000


class UIDebugConfig(BaseModel):
    show_memory_usage: bool = True
    show_retrieval_details: bool = True
    show_intent_analysis: bool = True


class UIConfig(BaseModel):
    debug: UIDebugConfig = UIDebugConfig()


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file_path: str = "logs/soul.log"
    backup_count: int = 30
    module_levels: Dict[str, str] = {}
    redact_fields: List[str] = ["api_key", "password", "token"]


class Settings(BaseModel):
    """全局配置"""

    # 服务配置
    host: str = "0.0.0.0"
    port: int = 8004
    debug: bool = False

    # API Key
    google_api_key: str = ""

    # 路径
    maker_output_path: str = "../video-analysis-maker/output"
    soul_data_path: str = "./soul_data"

    # 子配置
    persona: PersonaConfig = PersonaConfig()
    memory: MemoryConfig = MemoryConfig()
    cache: CacheConfig = CacheConfig()
    llm: LLMConfig = LLMConfig()
    analysis: AnalysisConfig = AnalysisConfig()
    streaming: StreamingConfig = StreamingConfig()
    ui: UIConfig = UIConfig()
    logging: LoggingConfig = LoggingConfig()

    @property
    def maker_output_dir(self) -> Path:
        path = Path(self.maker_output_path)
        if not path.is_absolute():
            path = BASE_DIR / path
        return path.resolve()

    @property
    def soul_data_dir(self) -> Path:
        path = Path(self.soul_data_path)
        if not path.is_absolute():
            path = BASE_DIR / path
        return path.resolve()


def _resolve_env_vars(value: Any) -> Any:
    """递归解析配置中的环境变量引用 ${VAR:default}"""
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        inner = value[2:-1]
        if ":" in inner:
            var_name, default = inner.split(":", 1)
        else:
            var_name, default = inner, ""
        return os.getenv(var_name, default)
    elif isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_resolve_env_vars(v) for v in value]
    return value


def load_settings() -> Settings:
    """加载配置：环境变量 + settings.yaml"""
    config_data: Dict[str, Any] = {}

    # 从 settings.yaml 加载
    yaml_path = BASE_DIR / "config" / "settings.yaml"
    if yaml_path.exists():
        with open(yaml_path, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f) or {}
            config_data = _resolve_env_vars(yaml_data)

    # 环境变量覆盖
    env_overrides = {
        "google_api_key": os.getenv("GOOGLE_API_KEY", ""),
        "host": os.getenv("SOUL_HOST", config_data.get("host", "0.0.0.0")),
        "port": int(os.getenv("SOUL_PORT", config_data.get("port", 8004))),
        "debug": os.getenv("SOUL_DEBUG", "false").lower() == "true",
        "maker_output_path": os.getenv(
            "MAKER_OUTPUT_PATH",
            config_data.get("maker_output_path", "../video-analysis-maker/output"),
        ),
        "soul_data_path": os.getenv(
            "SOUL_DATA_PATH",
            config_data.get("soul_data_path", "./soul_data"),
        ),
    }

    config_data.update({k: v for k, v in env_overrides.items() if v})

    return Settings(**config_data)


# 全局配置单例
settings = load_settings()
