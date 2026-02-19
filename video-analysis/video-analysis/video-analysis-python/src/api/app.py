"""
FastAPI 应用配置
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from src import __version__
from .routes import router

# 前端 HTML 文件路径
_FRONTEND_HTML = Path(__file__).resolve().parent.parent.parent.parent / "video-analysis-web" / "index.html"


def create_app() -> FastAPI:
    """创建FastAPI应用"""
    app = FastAPI(
        title="Video Downloader API",
        description="多平台视频下载服务 - 支持 YouTube, TikTok, Bilibili, 小红书",
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS配置 - 允许前端跨域访问
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",  # Vite默认端口
            "http://localhost:3000",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:3000",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "null",  # file:// 协议的 origin
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册路由
    app.include_router(router, prefix="/api")

    @app.get("/")
    async def root():
        """返回前端页面，如果 HTML 文件不存在则返回 API 信息"""
        if _FRONTEND_HTML.is_file():
            return FileResponse(_FRONTEND_HTML, media_type="text/html")
        return {
            "name": "Video Downloader API",
            "version": __version__,
            "docs": "/docs",
        }

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


# 应用实例
app = create_app()
