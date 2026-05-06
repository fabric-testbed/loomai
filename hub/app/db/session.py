"""Async database engine and session factory."""

from __future__ import annotations

import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.db.models import Base

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async DB session."""
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    """Create all tables if they don't exist, and migrate schema."""
    logger.info("Initializing database tables")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Migrate: add columns if missing (SQLite create_all won't alter existing tables).
        migrations = [
            ("token_stores", "project_id", "VARCHAR(255)"),
            ("token_stores", "projects_json", "TEXT"),
            ("users", "bastion_login", "VARCHAR(255)"),
        ]
        for table, col, col_type in migrations:
            try:
                await conn.execute(
                    __import__("sqlalchemy").text(
                        f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"
                    )
                )
                logger.info("Migrated %s: added %s column", table, col)
            except Exception:
                pass  # Column already exists

    logger.info("Database tables ready")
