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
        persona_name="测试",
        persona_type=PersonaType.INFLUENCER,
        system_prompt="你是一个测试",
        common_phrases=["兄弟们！"],
    )
    manager.list_available_personas.return_value = [
        {"name": "测试", "has_knowledge_base": True, "has_system_prompt": True, "video_count": 5}
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
        id="test-user-id", name="测试用户",
        is_anonymous=False, is_registered=True,
    )
    manager.list_users.return_value = [
        UserProfile(id="test-user-id", name="测试用户",
                    is_anonymous=False, is_registered=True)
    ]
    return manager


@pytest.fixture
def mock_anonymous_user_manager():
    """Mock 匿名用户管理器"""
    from storage.models.user import UserProfile

    manager = AsyncMock()
    manager.get_user.return_value = UserProfile(
        id="anon-user-id", name="访客_abc123",
        is_anonymous=True, is_registered=False,
    )
    return manager


@pytest.fixture
def mock_preferences_repo():
    """Mock 偏好仓库"""
    from storage.models.preferences import UserPreferences

    repo = AsyncMock()
    repo.get.return_value = UserPreferences(user_id="anon-user-id")
    repo.merge_from_conversation.return_value = UserPreferences(
        user_id="anon-user-id",
        interests=["AI", "编程"],
        collection_progress={"interests": True, "recent_topics": True},
    )
    return repo


@pytest.fixture
def sample_chat_request():
    """示例对话请求"""
    return {
        "user_id": "test-user-id",
        "soul": "测试",
        "message": "今天AI应用怎么看？",
        "model": "gemini-2.5-flash",
    }


@pytest.fixture
def sample_soul_state():
    """示例 SoulState（注册用户）"""
    return {
        "user_id": "test-user-id",
        "soul_name": "测试",
        "user_message": "今天AI应用怎么看？",
        "model": "gemini-2.5-flash",
        "user_name": "测试用户",
        "is_anonymous": False,
        "is_registered": True,
        "user_preferences": {},
        "turn_count": 0,
        "intent": "chat",
        "needs_soul_knowledge": False,
        "needs_memory_recall": False,
        "memory_keywords": [],
        "soul_context": [],
        "memory_context": None,
        "detailed_history": None,
        "needs_detailed_history": False,
        "today_messages": [],
        "preview_summary": {},
        "system_prompt": "你是一个测试",
        "response": "这是的原始回复",
        "sources": [],
        "debug_info": {},
    }


@pytest.fixture
def sample_anonymous_state():
    """示例 SoulState（匿名用户）"""
    return {
        "user_id": "anon-user-id",
        "soul_name": "测试",
        "user_message": "你好，我想了解AI",
        "model": "gemini-2.5-flash",
        "user_name": "访客_abc123",
        "is_anonymous": True,
        "is_registered": False,
        "user_preferences": {
            "user_id": "anon-user-id",
            "interests": [],
            "visit_motivation": None,
            "personality_type": None,
            "communication_style": None,
            "recent_topics": [],
            "mood_history": [],
            "knowledge_level": {},
            "collection_progress": {},
        },
        "turn_count": 2,
        "intent": "chat",
        "needs_soul_knowledge": False,
        "needs_memory_recall": False,
        "memory_keywords": [],
        "soul_context": [],
        "memory_context": None,
        "detailed_history": None,
        "needs_detailed_history": False,
        "today_messages": [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好呀！"},
        ],
        "preview_summary": {},
        "system_prompt": "你是一个测试",
        "response": "AI技术发展非常迅速，目前在很多领域都有应用。",
        "sources": [],
        "debug_info": {},
    }


# 标记: pytest -m "not real_llm"  只运行 mock 测试
# 标记: pytest -m "real_llm"      只运行真实 LLM 测试
