from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .router import api_router
from .startup import init_models

app = FastAPI(title="Assigny API", version="0.1.0")

app.add_middleware(
	CORSMiddleware,
	allow_origins=["*"],
	allow_credentials=True,
	allow_methods=["*"],
	allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup() -> None:
	await init_models()


@app.get("/health")
async def health():
	return {"status": "ok"}


app.include_router(api_router) 