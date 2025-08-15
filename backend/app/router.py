from __future__ import annotations

from fastapi import APIRouter

from .agent import router as agent_router
 
api_router = APIRouter()
api_router.include_router(agent_router)


@api_router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "assigny-api"} 