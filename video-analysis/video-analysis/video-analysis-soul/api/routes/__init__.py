from fastapi import APIRouter

from api.routes.auth import router as auth_router
from api.routes.chat import router as chat_router
from api.routes.personas import router as personas_router
from api.routes.users import router as users_router
from api.routes.history import router as history_router
from api.routes.system import router as system_router

api_router = APIRouter(prefix="/api/soul")

api_router.include_router(system_router, tags=["system"])
api_router.include_router(auth_router, tags=["auth"])
api_router.include_router(personas_router, tags=["personas"])
api_router.include_router(users_router, tags=["users"])
api_router.include_router(history_router, tags=["history"])
api_router.include_router(chat_router, tags=["chat"])
