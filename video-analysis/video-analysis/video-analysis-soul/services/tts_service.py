"""TTS 语音合成服务 - 通过 HTTP 调用 voice-cloning API"""

from typing import Any, Dict, Optional

import httpx

from common.config import settings
from common.logger import get_logger

logger = get_logger(__name__)


class TTSService:
    """轻量 async HTTP 客户端，调用 voice-cloning 服务合成语音"""

    def __init__(self):
        cfg = settings.tts
        self._base_url = cfg.voice_service_url.rstrip("/")
        self._endpoint = cfg.synthesize_endpoint
        self._timeout = cfg.timeout_seconds
        self._default_speed = cfg.speed
        self._default_emotion = cfg.emotion
        self._max_text_length = cfg.max_text_length
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        """获取或创建持久 HTTP 客户端"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout, connect=10.0),
            )
        return self._client

    async def close(self):
        """关闭持久 HTTP 客户端"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def synthesize(
        self,
        text: str,
        soul_name: str,
        speed: Optional[float] = None,
        emotion: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        合成语音。

        返回 {"audio_base64": str, "format": str, "duration_seconds": float} 或 None。
        所有异常均捕获并返回 None（优雅降级）。
        """
        if not text or len(text) > self._max_text_length:
            if text and len(text) > self._max_text_length:
                logger.debug("Text too long for TTS (%d chars), skipping", len(text))
            return None

        url = self._base_url + self._endpoint
        payload = {
            "soul_name": soul_name,
            "text": text,
            "speed": speed or self._default_speed,
            "emotion": emotion or self._default_emotion,
        }

        try:
            logger.debug("TTS request: url=%s, soul=%s, text_len=%d", url, soul_name, len(text))
            client = self._get_client()
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

            if not data.get("success") or not data.get("audio_base64"):
                logger.warning("TTS API returned unsuccessful: %s", data.get("error", "unknown"))
                return None

            logger.info("TTS synthesis OK: %.1fs audio, %d bytes base64",
                        data.get("duration_seconds", 0), len(data["audio_base64"]))
            return {
                "audio_base64": data["audio_base64"],
                "format": data.get("format", "wav"),
                "duration_seconds": data.get("duration_seconds", 0),
            }
        except httpx.ConnectError:
            logger.debug("TTS service unavailable (connection refused)")
            return None
        except httpx.TimeoutException as e:
            logger.warning("TTS request timed out (%.0fs limit): %s", self._timeout, type(e).__name__)
            return None
        except Exception as e:
            logger.warning("TTS synthesis failed [%s]: %r", type(e).__name__, e, exc_info=True)
            return None

    async def is_available(self) -> bool:
        """健康检查：尝试连接 voice-cloning 服务"""
        try:
            client = self._get_client()
            resp = await client.get(self._base_url + "/api/voice/status")
            return resp.status_code == 200
        except Exception:
            return False
