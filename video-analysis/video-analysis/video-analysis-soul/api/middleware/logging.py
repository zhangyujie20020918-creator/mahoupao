"""请求日志中间件"""

import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from common.logger import get_logger

logger = get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """请求日志中间件"""

    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())[:8]
        start_time = time.time()

        # 注入 request_id
        request.state.request_id = request_id

        logger.info(
            f"Request start: {request.method} {request.url.path}",
            extra={"request_id": request_id},
        )

        response = await call_next(request)

        duration = time.time() - start_time
        logger.info(
            f"Request end: {request.method} {request.url.path} "
            f"status={response.status_code} duration={duration:.3f}s",
            extra={"request_id": request_id},
        )

        response.headers["X-Request-ID"] = request_id
        return response
