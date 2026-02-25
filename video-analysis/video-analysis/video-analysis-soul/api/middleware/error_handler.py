"""全局异常处理中间件"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from common.exceptions import (
    SoulBaseError,
    PersonaNotFoundError,
    RegistrationError,
    UserNotFoundError,
    VerificationError,
    LLMError,
)
from common.logger import get_logger

logger = get_logger(__name__)


def register_error_handlers(app: FastAPI) -> None:
    """注册全局异常处理器"""

    @app.exception_handler(UserNotFoundError)
    async def user_not_found_handler(request: Request, exc: UserNotFoundError):
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": exc.message, "detail": exc.detail},
        )

    @app.exception_handler(PersonaNotFoundError)
    async def persona_not_found_handler(request: Request, exc: PersonaNotFoundError):
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": exc.message, "detail": exc.detail},
        )

    @app.exception_handler(VerificationError)
    async def verification_error_handler(request: Request, exc: VerificationError):
        return JSONResponse(
            status_code=403,
            content={"success": False, "error": exc.message, "detail": exc.detail},
        )

    @app.exception_handler(RegistrationError)
    async def registration_error_handler(request: Request, exc: RegistrationError):
        return JSONResponse(
            status_code=409,
            content={"success": False, "error": exc.message, "detail": exc.detail},
        )

    @app.exception_handler(LLMError)
    async def llm_error_handler(request: Request, exc: LLMError):
        logger.error(f"LLM Error: {exc.message}")
        return JSONResponse(
            status_code=503,
            content={
                "success": False,
                "error": "LLM service unavailable",
                "detail": exc.message,
            },
        )

    @app.exception_handler(SoulBaseError)
    async def soul_error_handler(request: Request, exc: SoulBaseError):
        logger.error(f"Soul Error: {exc.message}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": exc.message, "detail": exc.detail},
        )

    @app.exception_handler(Exception)
    async def general_error_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled error: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "Internal server error",
                "detail": str(exc),
            },
        )
