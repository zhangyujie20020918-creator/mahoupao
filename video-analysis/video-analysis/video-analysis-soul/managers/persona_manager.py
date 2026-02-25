"""Persona 管理器 - 从 video-analysis-maker 输出加载 Persona"""

import json
from pathlib import Path
from typing import Dict, List, Optional

from common.config import settings
from common.exceptions import PersonaLoadError, PersonaNotFoundError
from common.logger import get_logger
from services.embedding_service import EmbeddingService
from storage.models.persona import PersonaMetadata, PersonaType
from storage.vector_stores.chroma_store import ChromaStore, SearchResult

logger = get_logger(__name__)


class PersonaManager:
    """
    从 video-analysis-maker 输出加载 Persona

    职责:
    - 扫描 maker 输出目录，发现可用 Persona
    - 读取 persona.json + system_prompt.txt 构建 PersonaMetadata
    - 连接 ChromaDB，使用 BGE embedding 搜索知识库
    - 缓存已加载的 Persona，避免重复 IO
    """

    def __init__(self, embedding_service: EmbeddingService):
        self.maker_output_dir = settings.maker_output_dir
        self._persona_cache: Dict[str, PersonaMetadata] = {}
        self._chroma_store = ChromaStore()
        self._embedding_service = embedding_service

    # ---- Persona 加载 ----

    def load_persona(self, persona_name: str) -> PersonaMetadata:
        """
        加载 Persona 元数据

        读取顺序:
        1. 检查缓存
        2. 读取 persona.json（字段映射）
        3. 读取 system_prompt.txt（优先覆盖 persona.json 中的 system_prompt）
        4. 统计 optimized_texts 和 chroma_db
        5. 构建 PersonaMetadata 并缓存
        """
        if persona_name in self._persona_cache:
            return self._persona_cache[persona_name]

        persona_dir = self.maker_output_dir / persona_name
        if not persona_dir.exists():
            raise PersonaNotFoundError(
                f"Persona 未找到: {persona_name}",
                detail=f"目录不存在: {persona_dir}",
            )

        try:
            metadata_dict = self._read_persona_json(persona_dir)
            metadata_dict = self._read_system_prompt(persona_dir, metadata_dict)
            metadata_dict = self._collect_stats(persona_dir, metadata_dict)

            metadata_dict["persona_name"] = persona_name
            metadata_dict["output_dir"] = str(persona_dir)

            metadata = PersonaMetadata(**metadata_dict)
            self._persona_cache[persona_name] = metadata

            logger.info(
                f"Loaded persona: {persona_name} "
                f"(videos={metadata.video_count}, knowledge={metadata.knowledge_count})"
            )
            return metadata

        except PersonaNotFoundError:
            raise
        except Exception as e:
            raise PersonaLoadError(
                f"Persona 加载失败: {persona_name}",
                detail=str(e),
            )

    def _read_persona_json(self, persona_dir: Path) -> dict:
        """读取并映射 persona.json"""
        persona_json_path = persona_dir / "persona.json"
        if not persona_json_path.exists():
            logger.warning(f"persona.json not found: {persona_json_path}")
            return {}

        with open(persona_json_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        return self._map_maker_fields(raw_data)

    def _read_system_prompt(self, persona_dir: Path, metadata_dict: dict) -> dict:
        """读取 system_prompt.txt（优先级高于 persona.json 中的字段）"""
        system_prompt_path = persona_dir / "system_prompt.txt"
        if system_prompt_path.exists():
            with open(system_prompt_path, "r", encoding="utf-8") as f:
                metadata_dict["system_prompt"] = f.read().strip()
        return metadata_dict

    def _collect_stats(self, persona_dir: Path, metadata_dict: dict) -> dict:
        """统计视频数量和 ChromaDB 信息"""
        # ChromaDB 路径
        chroma_db_path = persona_dir / "chroma_db"
        if chroma_db_path.exists():
            metadata_dict["chroma_db_path"] = str(chroma_db_path)

        # 统计 optimized_texts 中的视频数量（.json 文件 = 1个视频）
        optimized_dir = persona_dir / "optimized_texts"
        if optimized_dir.exists():
            video_count = len(list(optimized_dir.glob("*.json")))
            metadata_dict["video_count"] = video_count

        return metadata_dict

    def _map_maker_fields(self, raw_data: dict) -> dict:
        """
        映射 maker 的 persona.json 字段到 soul 的 PersonaMetadata 字段

        maker persona.json 实际字段:
        - blogger_name, speaking_style, common_phrases, topic_expertise,
        - personality_traits, tone, target_audience, content_patterns, system_prompt
        """
        field_mapping = {
            "blogger_name": "persona_name",
            "speaking_style": "speaking_style",
            "common_phrases": "common_phrases",
            "topic_expertise": "topic_expertise",
            "personality_traits": "personality_traits",
            "tone": "tone",
            "target_audience": "target_audience",
            "content_patterns": "content_patterns",
            "system_prompt": "system_prompt",
        }

        mapped = {}
        for maker_key, soul_key in field_mapping.items():
            if maker_key in raw_data and raw_data[maker_key]:
                mapped[soul_key] = raw_data[maker_key]

        return mapped

    # ---- 知识库连接 ----

    def connect_knowledge_base(self, persona_name: str) -> None:
        """
        连接 Persona 的 ChromaDB 知识库

        首次搜索前需要调用，或由 search_knowledge 自动触发。
        如果 HNSW 索引损坏，自动从 optimized_texts/ 重建。
        """
        metadata = self.load_persona(persona_name)
        if not metadata.chroma_db_path:
            raise PersonaNotFoundError(
                f"ChromaDB 未找到: {persona_name}",
                detail=f"Persona 目录中没有 chroma_db/",
            )

        collection = self._chroma_store.connect(
            persona_name, metadata.chroma_db_path
        )

        # 验证索引是否可用
        try:
            metadata.knowledge_count = collection.count()
        except Exception as e:
            logger.warning(
                f"ChromaDB index corrupted for {persona_name}: {e}. Rebuilding..."
            )
            self._rebuild_knowledge_base(persona_name, metadata)

    def _rebuild_knowledge_base(self, persona_name: str, metadata: PersonaMetadata) -> None:
        """从 optimized_texts 重建 ChromaDB 索引"""
        persona_dir = Path(metadata.output_dir)
        optimized_dir = persona_dir / "optimized_texts"

        if not optimized_dir.exists():
            raise PersonaLoadError(
                f"无法重建知识库: {persona_name}",
                detail=f"optimized_texts 目录不存在: {optimized_dir}",
            )

        # 确保 embedding 模型已加载
        if not self._embedding_service.is_initialized:
            self._embedding_service.initialize()

        count = self._chroma_store.rebuild_from_optimized_texts(
            persona_name=persona_name,
            db_path=metadata.chroma_db_path,
            optimized_texts_dir=str(optimized_dir),
            encode_fn=self._embedding_service.encode,
        )

        metadata.knowledge_count = count
        logger.info(f"Knowledge base rebuilt for {persona_name}: {count} documents")

    def rebuild_knowledge_base(self, persona_name: str) -> int:
        """
        手动触发重建知识库（公开接口）

        Returns:
            写入的文档数量
        """
        metadata = self.load_persona(persona_name)
        self._rebuild_knowledge_base(persona_name, metadata)
        return metadata.knowledge_count

    # ---- 知识库搜索 ----

    def search_knowledge(
        self,
        persona_name: str,
        query: str,
        n_results: int = 5,
        context_window: int = 2,
    ) -> List[SearchResult]:
        """
        搜索 Persona 知识库

        使用与 maker 相同的 BGE 模型生成查询 embedding，
        然后在 ChromaDB 中搜索最相关的视频片段。

        Args:
            persona_name: Persona 名称
            query: 用户查询文本
            n_results: 返回结果数量
            context_window: 上下文窗口（前后各取几段）

        Returns:
            SearchResult 列表
        """
        # 确保知识库已连接（含自动重建）
        stats = self._chroma_store.get_stats(persona_name)
        if not stats.get("connected"):
            self.connect_knowledge_base(persona_name)

        # 使用 BGE 模型编码查询
        if not self._embedding_service.is_initialized:
            self._embedding_service.initialize()
        query_embedding = self._embedding_service.encode_query(query)

        # 搜索
        results = self._chroma_store.search(
            persona_name=persona_name,
            query_embedding=query_embedding,
            n_results=n_results,
            context_window=context_window,
        )

        return results

    # ---- 列表 & 信息 ----

    def list_available_personas(self) -> List[Dict]:
        """扫描 maker 输出目录，列出所有可用 Persona"""
        if not self.maker_output_dir.exists():
            logger.warning(f"Maker output directory not found: {self.maker_output_dir}")
            return []

        personas = []
        for d in sorted(self.maker_output_dir.iterdir()):
            if not d.is_dir():
                continue

            has_persona_json = (d / "persona.json").exists()
            has_system_prompt = (d / "system_prompt.txt").exists()
            has_chroma = (d / "chroma_db").exists()

            # 至少有 persona.json 或 system_prompt.txt 才算有效
            if not (has_persona_json or has_system_prompt):
                continue

            # 统计视频数
            optimized_dir = d / "optimized_texts"
            video_count = len(list(optimized_dir.glob("*.json"))) if optimized_dir.exists() else 0

            personas.append({
                "name": d.name,
                "has_knowledge_base": has_chroma,
                "has_system_prompt": has_system_prompt,
                "video_count": video_count,
            })

        return personas

    def get_persona_detail(self, persona_name: str) -> Dict:
        """获取 Persona 详细信息（含知识库统计）"""
        metadata = self.load_persona(persona_name)

        detail = {
            "name": metadata.persona_name,
            "type": metadata.persona_type.value,
            "speaking_style": metadata.speaking_style,
            "tone": metadata.tone,
            "common_phrases": metadata.common_phrases,
            "topic_expertise": metadata.topic_expertise,
            "personality_traits": metadata.personality_traits,
            "target_audience": metadata.target_audience,
            "content_patterns": metadata.content_patterns,
            "video_count": metadata.video_count,
            "knowledge_count": metadata.knowledge_count,
            "has_system_prompt": bool(metadata.system_prompt),
            "has_knowledge_base": bool(metadata.chroma_db_path),
        }

        # 如果已连接 ChromaDB，补充实时统计
        stats = self._chroma_store.get_stats(persona_name)
        if stats.get("connected"):
            detail["knowledge_count"] = stats.get("document_count", 0)

        return detail

    def reload_persona(self, persona_name: str) -> PersonaMetadata:
        """强制重新加载 Persona（清除缓存）"""
        self._persona_cache.pop(persona_name, None)
        self._chroma_store.close(persona_name)
        return self.load_persona(persona_name)

    # ---- 生命周期 ----

    def close(self) -> None:
        """释放所有资源"""
        self._chroma_store.close()
        self._persona_cache.clear()
        logger.info("PersonaManager closed")
