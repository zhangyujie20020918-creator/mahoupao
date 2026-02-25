"""FastAPI 入口"""

import sys
from contextlib import asynccontextmanager
from pathlib import Path

# 添加项目根目录到 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.middleware.error_handler import register_error_handlers
from api.middleware.logging import RequestLoggingMiddleware
from api.routes import api_router
from common.config import settings
from common.logger import setup_logging, get_logger
from core.engine import SoulEngine

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动
    setup_logging(settings.logging)
    logger.info("Starting Video-Analysis-Soul...")

    engine = SoulEngine()
    await engine.start()
    app.state.engine = engine

    logger.info(f"Server running on {settings.host}:{settings.port}")
    yield

    # 关闭
    logger.info("Shutting down...")
    await engine.stop()


app = FastAPI(
    title="Video-Analysis-Soul",
    description="智能对话系统 - 基于人格与长期记忆",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 请求日志
app.add_middleware(RequestLoggingMiddleware)

# 异常处理
register_error_handlers(app)

# 路由
app.include_router(api_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
