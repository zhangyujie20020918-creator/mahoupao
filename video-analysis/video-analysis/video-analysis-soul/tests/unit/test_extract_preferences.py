"""extract_preferences 节点单元测试"""

import json

import pytest
from unittest.mock import AsyncMock, patch


class TestExtractPreferences:
    """extract_preferences 节点测试"""

    @pytest.mark.asyncio
    async def test_noop_for_registered_user(
        self, sample_soul_state, mock_llm_service, mock_preferences_repo
    ):
        """注册用户应直接返回空 dict"""
        from core.graph.nodes.extract_preferences import extract_preferences

        result = await extract_preferences(
            sample_soul_state,
            llm_service=mock_llm_service,
            preferences_repo=mock_preferences_repo,
        )
        assert result == {}
        mock_llm_service.analyze.assert_not_called()
        mock_preferences_repo.merge_from_conversation.assert_not_called()

    @pytest.mark.asyncio
    async def test_noop_when_disabled(
        self, sample_anonymous_state, mock_llm_service, mock_preferences_repo
    ):
        """配置禁用时不执行提取"""
        from core.graph.nodes.extract_preferences import extract_preferences

        with patch("core.graph.nodes.extract_preferences.settings") as mock_settings:
            mock_settings.connection_agent.enabled = False
            result = await extract_preferences(
                sample_anonymous_state,
                llm_service=mock_llm_service,
                preferences_repo=mock_preferences_repo,
            )
        assert result == {}

    @pytest.mark.asyncio
    async def test_noop_when_too_few_messages(
        self, sample_anonymous_state, mock_llm_service, mock_preferences_repo
    ):
        """消息太少时不提取"""
        from core.graph.nodes.extract_preferences import extract_preferences

        # 只有 1 轮对话 (2条 today + 当前 2条 = 4条，刚好够)
        # 但如果 today 是空的 (0条 + 当前 2条 = 2条，不够)
        sample_anonymous_state["today_messages"] = []
        result = await extract_preferences(
            sample_anonymous_state,
            llm_service=mock_llm_service,
            preferences_repo=mock_preferences_repo,
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_noop_when_no_preferences_repo(
        self, sample_anonymous_state, mock_llm_service
    ):
        """没有 preferences_repo 时不提取"""
        from core.graph.nodes.extract_preferences import extract_preferences

        result = await extract_preferences(
            sample_anonymous_state,
            llm_service=mock_llm_service,
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_extracts_on_turn_2(
        self, sample_anonymous_state, mock_llm_service, mock_preferences_repo
    ):
        """第 2 轮提取偏好"""
        from core.graph.nodes.extract_preferences import extract_preferences

        # today_messages 有 2 条，加上当前轮 2 条 = 4 条，turn_count = 2
        extracted = {
            "interests": ["AI"],
            "visit_motivation": "学习技术",
            "personality_type": None,
            "communication_style": None,
            "recent_topics": ["人工智能"],
            "knowledge_level": {},
        }
        mock_llm_service.analyze.return_value = json.dumps(extracted, ensure_ascii=False)

        result = await extract_preferences(
            sample_anonymous_state,
            llm_service=mock_llm_service,
            preferences_repo=mock_preferences_repo,
        )

        assert "user_preferences" in result
        mock_llm_service.analyze.assert_called_once()
        mock_preferences_repo.merge_from_conversation.assert_called_once()

    @pytest.mark.asyncio
    async def test_extracts_on_turn_3(
        self, sample_anonymous_state, mock_llm_service, mock_preferences_repo
    ):
        """第 3 轮（每 3 轮的倍数）提取偏好"""
        from core.graph.nodes.extract_preferences import extract_preferences

        # 需要 today_messages 有 4 条，加上当前 2 条 = 6 条，turn_count = 3
        sample_anonymous_state["today_messages"] = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好呀！"},
            {"role": "user", "content": "讲讲AI"},
            {"role": "assistant", "content": "AI很有趣"},
        ]

        extracted = {
            "interests": ["AI", "编程"],
            "visit_motivation": None,
            "personality_type": None,
            "communication_style": None,
            "recent_topics": ["AI"],
            "knowledge_level": {},
        }
        mock_llm_service.analyze.return_value = json.dumps(extracted, ensure_ascii=False)

        result = await extract_preferences(
            sample_anonymous_state,
            llm_service=mock_llm_service,
            preferences_repo=mock_preferences_repo,
        )

        assert "user_preferences" in result
        mock_llm_service.analyze.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_non_trigger_turns(
        self, sample_anonymous_state, mock_llm_service, mock_preferences_repo
    ):
        """非触发轮次应跳过提取"""
        from core.graph.nodes.extract_preferences import extract_preferences

        # today 6条 + 当前 2条 = 8条，turn_count = 4，不是 2 也不是 3 的倍数
        sample_anonymous_state["today_messages"] = [
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "reply1"},
            {"role": "user", "content": "msg2"},
            {"role": "assistant", "content": "reply2"},
            {"role": "user", "content": "msg3"},
            {"role": "assistant", "content": "reply3"},
        ]

        result = await extract_preferences(
            sample_anonymous_state,
            llm_service=mock_llm_service,
            preferences_repo=mock_preferences_repo,
        )

        assert result == {}
        mock_llm_service.analyze.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_llm_error_gracefully(
        self, sample_anonymous_state, mock_llm_service, mock_preferences_repo
    ):
        """LLM 调用失败时应返回空 dict"""
        from core.graph.nodes.extract_preferences import extract_preferences

        mock_llm_service.analyze.side_effect = Exception("LLM error")

        result = await extract_preferences(
            sample_anonymous_state,
            llm_service=mock_llm_service,
            preferences_repo=mock_preferences_repo,
        )

        assert result == {}

    @pytest.mark.asyncio
    async def test_handles_invalid_json_gracefully(
        self, sample_anonymous_state, mock_llm_service, mock_preferences_repo
    ):
        """LLM 返回无效 JSON 时应返回空 dict"""
        from core.graph.nodes.extract_preferences import extract_preferences

        mock_llm_service.analyze.return_value = "这不是一个有效的JSON"

        result = await extract_preferences(
            sample_anonymous_state,
            llm_service=mock_llm_service,
            preferences_repo=mock_preferences_repo,
        )

        assert result == {}

    @pytest.mark.asyncio
    async def test_handles_markdown_wrapped_json(
        self, sample_anonymous_state, mock_llm_service, mock_preferences_repo
    ):
        """LLM 返回 markdown 包裹的 JSON 时应正确解析"""
        from core.graph.nodes.extract_preferences import extract_preferences

        extracted = {
            "interests": ["AI"],
            "visit_motivation": None,
            "personality_type": None,
            "communication_style": None,
            "recent_topics": [],
            "knowledge_level": {},
        }
        mock_llm_service.analyze.return_value = f"```json\n{json.dumps(extracted)}\n```"

        result = await extract_preferences(
            sample_anonymous_state,
            llm_service=mock_llm_service,
            preferences_repo=mock_preferences_repo,
        )

        assert "user_preferences" in result
        mock_preferences_repo.merge_from_conversation.assert_called_once()
