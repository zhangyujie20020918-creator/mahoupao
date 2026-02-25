"""测试配置"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

# 添加项目根目录到 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def mock_llm_service():
    """Mock LLM 服务"""
    service = AsyncMock()
    service.generate.return_value = "这是一个模拟的回复"
    service.generate_stream.return_value = iter(["这是", "一个", "模拟", "的回复"])
    service.analyze.return_value = '{"intent": "question", "confidence": 0.9}'
    service.summarize.return_value = '{"topics_discussed": ["测试话题"]}'
    return service


@pytest.fixture
def mock_persona_manager():
    """Mock Persona 管理器"""
    from unittest.mock import MagicMock
    from storage.models.persona import PersonaMetadata, PersonaType
    from storage.vector_stores.chroma_store import SearchResult

    manager = MagicMock()
    manager.load_persona.return_value = PersonaMetadata(
        persona_name="测试博主",
        persona_type=PersonaType.INFLUENCER,
        system_prompt="你是一个测试博主",
        common_phrases=["兄弟们！"],
    )
    manager.list_available_personas.return_value = [
        {"name": "测试博主", "has_knowledge_base": True, "has_system_prompt": True, "video_count": 5}
    ]
    manager.search_knowledge.return_value = [
        SearchResult(
            text="测试内容", video_title="测试视频", segment_index=0,
            start=0.0, end=5.0, distance=0.1,
            context_before=[], context_after=[],
        )
    ]
    return manager


@pytest.fixture
def mock_user_manager():
    """Mock 用户管理器"""
    from storage.models.user import UserProfile

    manager = AsyncMock()
    manager.get_user.return_value = UserProfile(
        id="test-user-id", name="测试用户"
    )
    manager.list_users.return_value = [
        UserProfile(id="test-user-id", name="测试用户")
    ]
    return manager


@pytest.fixture
def sample_chat_request():
    """示例对话请求"""
    return {
        "user_id": "test-user-id",
        "blogger": "测试博主",
        "message": "今天AI应用怎么看？",
        "model": "gemini-2.5-flash",
    }


# 标记: pytest -m "not real_llm"  只运行 mock 测试
# 标记: pytest -m "real_llm"      只运行真实 LLM 测试
