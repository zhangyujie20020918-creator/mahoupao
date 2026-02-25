"""对话历史接口"""

from fastapi import APIRouter, HTTPException, Request

from api.schemas.common import BaseResponse

router = APIRouter()


@router.get("/history/{user_id}/{blogger}")
async def get_history(
    user_id: str, blogger: str, request: Request, date: str = None
) -> BaseResponse:
    """获取对话历史"""
    engine = request.app.state.engine

    if date:
        # 获取指定日期
        conv = await engine.memory_manager.get_conversation_by_date(
            user_id, blogger, date
        )
        if not conv:
            return BaseResponse(data={"messages": [], "date": date})
        return BaseResponse(
            data={
                "date": conv.date,
                "messages": [m.model_dump(mode="json") for m in conv.messages],
                "message_count": conv.message_count,
            }
        )
    else:
        # 获取今日对话
        conv = await engine.memory_manager.get_today_conversation(user_id, blogger)
        dates = await engine.memory_manager.get_conversation_dates(user_id, blogger)
        return BaseResponse(
            data={
                "today": {
                    "date": conv.date,
                    "messages": [m.model_dump(mode="json") for m in conv.messages],
                    "message_count": conv.message_count,
                },
                "available_dates": dates,
            }
        )
