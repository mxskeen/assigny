from __future__ import annotations

import asyncio

from sqlalchemy import text

from .db import Base, engine
from . import models  # noqa: F401
from .seed import seed


async def init_models() -> None:
	async with engine.begin() as conn:
		await conn.run_sync(Base.metadata.create_all)
	# Auto-seed demo data (idempotent)
	await seed()


if __name__ == "__main__":
	asyncio.run(init_models()) 