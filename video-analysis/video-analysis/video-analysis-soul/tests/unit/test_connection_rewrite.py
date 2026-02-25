"""connection_rewrite 节点单元测试"""

import pytest
from unittest.mock import AsyncMock, patch


class TestConnectionRewrite:
    """connection_rewrite 节点测试"""

    @pytest.mark.asyncio
    async def test_noop_for_registered_user(self, sample_soul_state, mock_llm_service):
        """注册用户应直接返回空 dict"""
        from core.graph.nodes.connection_rewrite import connection_rewrite

        result = await connection_rewrite(
            sample_soul_state,
            llm_service=mock_llm_service,
        )
        assert result == {}
        mock_llm_service.analyze.assert_not_called()

    @pytest.mark.asyncio
    async def test_noop_when_not_anonymous(self, sample_soul_state, mock_llm_service):
        """is_anonymous=False 时不执行改写"""
        from core.graph.nodes.connection_rewrite import connection_rewrite

        sample_soul_state["is_anonymous"] = False
        result = await connection_rewrite(
            sample_soul_state,
            llm_service=mock_llm_service,
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_noop_when_disabled(self, sample_anonymous_state, mock_llm_service):
        """配置禁用时不执行改写"""
        from core.graph.nodes.connection_rewrite import connection_rewrite

        with patch("core.graph.nodes.connection_rewrite.settings") as mock_settings:
            mock_settings.connection_agent.enabled = False
            result = await connection_rewrite(
                sample_anonymous_state,
                llm_service=mock_llm_service,
            )
        assert result == {}

    @pytest.mark.asyncio
    async def test_noop_when_empty_response(self, sample_anonymous_state, mock_llm_service):
        """空回复时不执行改写"""
        from core.graph.nodes.connection_rewrite import connection_rewrite

        sample_anonymous_state["response"] = ""
        result = await connection_rewrite(
            sample_anonymous_state,
            llm_service=mock_llm_service,
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_rewrites_for_anonymous_user(self, sample_anonymous_state, mock_llm_service):
        """匿名用户应改写回复"""
        from core.graph.nodes.connection_rewrite import connection_rewrite

        mock_llm_service.analyze.return_value = "AI技术发展非常迅速！对了，你是对哪方面的AI比较感兴趣呢？"

        with patch("core.graph.nodes.connection_rewrite._PROMPT_TEMPLATE", "test {preferences} {turn_count} {missing_dimensions} {target_dimension} {original_response} {conversation} {nudge_threshold}"):
            result = await connection_rewrite(
                sample_anonymous_state,
                llm_service=mock_llm_service,
            )

        assert "response" in result
        assert result["response"] != sample_anonymous_state["response"]
        assert "debug_info" in result
        assert "connection_agent" in result["debug_info"]
        mock_llm_service.analyze.assert_called_once()

    @pytest.mark.asyncio
    async def test_preserves_original_on_llm_failure(self, sample_anonymous_state, mock_llm_service):
        """LLM 调用失败时保留原始回复"""
        from core.graph.nodes.connection_rewrite import connection_rewrite

        mock_llm_service.analyze.side_effect = Exception("LLM error")

        with patch("core.graph.nodes.connection_rewrite._PROMPT_TEMPLATE", "test {preferences} {turn_count} {missing_dimensions} {target_dimension} {original_response} {conversation} {nudge_threshold}"):
            result = await connection_rewrite(
                sample_anonymous_state,
                llm_service=mock_llm_service,
            )

        # 失败时返回空 dict，保留原始 response
        assert result == {}

    @pytest.mark.asyncio
    async def test_debug_info_contains_metadata(self, sample_anonymous_state, mock_llm_service):
        """debug_info 应包含连接助手元数据"""
        from core.graph.nodes.connection_rewrite import connection_rewrite

        mock_llm_service.analyze.return_value = "改写后的回复内容"

        with patch("core.graph.nodes.connection_rewrite._PROMPT_TEMPLATE", "test {preferences} {turn_count} {missing_dimensions} {target_dimension} {original_response} {conversation} {nudge_threshold}"):
            result = await connection_rewrite(
                sample_anonymous_state,
                llm_service=mock_llm_service,
            )

        debug = result["debug_info"]["connection_agent"]
        assert "original_length" in debug
        assert "rewritten_length" in debug
        assert "target_dimension" in debug
        assert "missing_dimensions" in debug
        assert "turn_count" in debug


class TestMissingDimensions:
    """missing_dimensions 计算测试"""

    def test_all_missing_when_empty_progress(self):
        """空进度时所有维度都缺失"""
        from core.graph.nodes.connection_rewrite import _get_missing_dimensions

        missing = _get_missing_dimensions({"collection_progress": {}})
        assert len(missing) == 5
        assert "interests" in missing

    def test_partial_missing(self):
        """部分维度已收集"""
        from core.graph.nodes.connection_rewrite import _get_missing_dimensions

        missing = _get_missing_dimensions({
            "collection_progress": {"interests": True, "visit_motivation": True}
        })
        assert "interests" not in missing
        assert "visit_motivation" not in missing
        assert "personality_type" in missing

    def test_none_missing_when_all_collected(self):
        """所有维度已收集"""
        from core.graph.nodes.connection_rewrite import _get_missing_dimensions

        missing = _get_missing_dimensions({
            "collection_progress": {
                "interests": True,
                "visit_motivation": True,
                "personality_type": True,
                "communication_style": True,
                "recent_topics": True,
            }
        })
        assert len(missing) == 0


class TestPickTargetDimension:
    """target_dimension 选择测试"""

    def test_picks_first_missing(self):
        """选择第一个未收集的维度"""
        from core.graph.nodes.connection_rewrite import _pick_target_dimension

        result = _pick_target_dimension(["personality_type", "communication_style"])
        assert result == "personality_type"

    def test_default_when_none_missing(self):
        """所有维度已收集时返回默认值"""
        from core.graph.nodes.connection_rewrite import _pick_target_dimension

        result = _pick_target_dimension([])
        assert result == "recent_topics"
