from __future__ import annotations

from fastapi import APIRouter

from .agent import router as agent_router

api_router = APIRouter()
api_router.include_router(agent_router) 