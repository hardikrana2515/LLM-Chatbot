from fastapi import APIRouter
from APIs.routes import user,authuser,conversation,messages

api_router = APIRouter()

api_router.include_router(user.router)
api_router.include_router(authuser.router)
api_router.include_router(conversation.router)
api_router.include_router(messages.router)
