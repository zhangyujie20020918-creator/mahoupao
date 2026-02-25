"""Chat 接口 (SSE 流式)"""

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from api.schemas.chat import ChatRequest
from api.schemas.common import BaseResponse
from common.exceptions import PersonaNotFoundError, UserNotFoundError
from common.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.post("/chat")
async def chat(body: ChatRequest, request: Request):
    """
    发送消息（SSE 流式响应）

    事件类型:
    - thinking: 分析中
    - searching: 检索中
    - message_start: 新消息气泡 (data: {sentence_id})
    - token: 回复内容片段 (data: {content, sentence_id})
    - sentence_end: 句子结束 (data: {sentence_id})
    - audio: 语音合成结果 (data: {sentence_id, audio_base64, format, duration_seconds})
    - done: 完成
    - error: 错误
    """
    engine = request.app.state.engine

    async def event_stream():
        try:
            async for event in engine.chat_stream(
                user_id=body.user_id,
                soul_name=body.soul,
                message=body.message,
                model=body.model,
            ):
                event_type = event.get("event", "token")
                event_data = json.dumps(event.get("data", {}), ensure_ascii=False)
                yield f"event: {event_type}\ndata: {event_data}\n\n"

        except UserNotFoundError as e:
            yield f"event: error\ndata: {json.dumps({'error': 'user_not_found', 'message': str(e)})}\n\n"
        except PersonaNotFoundError as e:
            yield f"event: error\ndata: {json.dumps({'error': 'persona_not_found', 'message': str(e)})}\n\n"
        except Exception as e:
            logger.error(f"Chat error: {e}", exc_info=True)
            yield f"event: error\ndata: {json.dumps({'error': 'internal_error', 'message': '服务暂时不可用，请稍后重试'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/preview/refresh")
async def refresh_preview(
    request: Request, user_id: str = None, soul: str = None
) -> BaseResponse:
    """强制刷新 Preview"""
    engine = request.app.state.engine

    if not user_id or not soul:
        raise HTTPException(
            status_code=400, detail="user_id and soul are required"
        )

    # TODO: 触发 Preview 重新总结
    return BaseResponse(message="Preview refresh triggered")
