from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .router import api_router
from .startup import init_models


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown."""
    await init_models()
    yield


app = FastAPI(
    title="Assigny API",
    description="Smart Doctor Appointment Assistant with MCP",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router) 