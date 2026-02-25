"""TTSService 单元测试"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from services.tts_service import TTSService


@pytest.fixture
def tts_service():
    """创建 TTSService 实例（使用默认配置）"""
    with patch("services.tts_service.settings") as mock_settings:
        mock_settings.tts.voice_service_url = "http://localhost:8003"
        mock_settings.tts.synthesize_endpoint = "/api/voice/synthesize"
        mock_settings.tts.timeout_seconds = 10.0
        mock_settings.tts.speed = 1.0
        mock_settings.tts.emotion = "neutral"
        mock_settings.tts.max_text_length = 500
        yield TTSService()


@pytest.mark.asyncio
async def test_synthesize_success(tts_service):
    """合成成功 → 返回音频数据"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "success": True,
        "audio_base64": "AAAA",
        "format": "wav",
        "duration_seconds": 2.5,
    }

    with patch("services.tts_service.httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await tts_service.synthesize(text="你好", soul_name="测试")

    assert result is not None
    assert result["audio_base64"] == "AAAA"
    assert result["format"] == "wav"
    assert result["duration_seconds"] == 2.5


@pytest.mark.asyncio
async def test_synthesize_service_unavailable(tts_service):
    """服务不可用 → 返回 None"""
    import httpx

    with patch("services.tts_service.httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await tts_service.synthesize(text="你好", soul_name="测试")

    assert result is None


@pytest.mark.asyncio
async def test_synthesize_text_too_long(tts_service):
    """文本过长 → 跳过返回 None"""
    long_text = "测" * 501
    result = await tts_service.synthesize(text=long_text, soul_name="测试")
    assert result is None


@pytest.mark.asyncio
async def test_synthesize_empty_text(tts_service):
    """空文本 → 返回 None"""
    result = await tts_service.synthesize(text="", soul_name="测试")
    assert result is None


@pytest.mark.asyncio
async def test_synthesize_api_error(tts_service):
    """API 返回错误 → 返回 None"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "success": False,
        "error": "模型未加载",
    }

    with patch("services.tts_service.httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await tts_service.synthesize(text="你好", soul_name="测试")

    assert result is None


@pytest.mark.asyncio
async def test_synthesize_http_500(tts_service):
    """HTTP 500 错误 → 返回 None"""
    import httpx

    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Server Error", request=MagicMock(), response=mock_response
    )

    with patch("services.tts_service.httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await tts_service.synthesize(text="你好", soul_name="测试")

    assert result is None


@pytest.mark.asyncio
async def test_is_available_true(tts_service):
    """健康检查 - 服务可用"""
    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch("services.tts_service.httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await tts_service.is_available()

    assert result is True


@pytest.mark.asyncio
async def test_is_available_false(tts_service):
    """健康检查 - 服务不可用"""
    import httpx

    with patch("services.tts_service.httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await tts_service.is_available()

    assert result is False
