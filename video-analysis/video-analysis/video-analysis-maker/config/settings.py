import os
from pathlib import Path
from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    # Gemini API
    gemini_api_key: str = Field(default="", env="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-1.5-pro", env="GEMINI_MODEL")

    # Embedding Model
    embedding_model: str = Field(default="BAAI/bge-large-zh-v1.5", env="EMBEDDING_MODEL")

    # Paths
    base_dir: Path = Path(__file__).parent.parent
    downloads_dir: Path = Field(default=None, env="DOWNLOADS_DIR")
    output_dir: Path = Field(default=None, env="OUTPUT_DIR")

    # ChromaDB
    chroma_collection_prefix: str = "soul_"

    # Processing Settings
    batch_size: int = 5  # 每批处理的视频数量
    context_window: int = 2  # 检索时扩展的上下文段落数

    class Config:
        env_file = ".env"
        extra = "ignore"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 设置默认路径
        if self.downloads_dir is None:
            self.downloads_dir = self.base_dir.parent / "downloads"
        elif not Path(self.downloads_dir).is_absolute():
            self.downloads_dir = self.base_dir / self.downloads_dir

        if self.output_dir is None:
            self.output_dir = self.base_dir / "output"
        elif not Path(self.output_dir).is_absolute():
            self.output_dir = self.base_dir / self.output_dir

        # 确保输出目录存在
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def get_soul_output_dir(self, soul_name: str) -> Path:
        """获取指定的输出目录"""
        soul_dir = self.output_dir / soul_name
        soul_dir.mkdir(parents=True, exist_ok=True)
        return soul_dir


@lru_cache()
def get_settings() -> Settings:
    return Settings()
