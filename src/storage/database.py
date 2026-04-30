"""
storage/database.py — PostgreSQL для Reels Bot
Читает опубликованные новости из общей БД (той же что у News Bot)
"""
import os
from datetime import datetime
from typing import Optional
import asyncpg
from loguru import logger

CREATE_REELS_TABLES = """
CREATE TABLE IF NOT EXISTS reels (
    id           SERIAL PRIMARY KEY,
    article_id   INTEGER,
    title        TEXT,
    script       TEXT,
    audio_path   TEXT,
    video_path   TEXT,
    status       TEXT DEFAULT 'pending',
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    error_msg    TEXT
);
CREATE INDEX IF NOT EXISTS idx_reels_status  ON reels(status);
CREATE INDEX IF NOT EXISTS idx_reels_article ON reels(article_id);
"""


class ReelsDatabase:
    def __init__(self):
        url = os.getenv("DATABASE_URL", "")
        if not url:
            raise ValueError("DATABASE_URL не задан")
        self.url = url.replace("postgres://", "postgresql://", 1)
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        self._pool = await asyncpg.create_pool(
            self.url, min_size=1, max_size=3,
            command_timeout=30, ssl="require",
        )
        async with self._pool.acquire() as conn:
            await conn.execute(CREATE_REELS_TABLES)
        logger.info("PostgreSQL (Reels) подключена ✓")

    async def close(self):
        if self._pool:
            await self._pool.close()

    async def reel_exists(self, article_id: int) -> bool:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM reels WHERE article_id=$1", article_id
            )
            return row is not None

    async def create_reel(self, article_id: int, title: str) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO reels (article_id, title) VALUES ($1,$2) RETURNING id",
                article_id, title,
            )
            return row["id"]

    async def update_reel(self, reel_id: int, **kwargs):
        if not kwargs:
            return
        sets = ", ".join(f"{k} = ${i+1}" for i, k in enumerate(kwargs))
        vals = list(kwargs.values()) + [reel_id]
        async with self._pool.acquire() as conn:
            await conn.execute(
                f"UPDATE reels SET {sets} WHERE id = ${len(vals)}", *vals
            )

    async def count_today(self) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) as cnt FROM reels WHERE created_at >= CURRENT_DATE AND status='done'"
            )
            return row["cnt"] if row else 0


class NewsReader:
    """Читает опубликованные статьи из общей PostgreSQL БД."""

    def __init__(self):
        url = os.getenv("DATABASE_URL", "")
        self.url = url.replace("postgres://", "postgresql://", 1)

    async def get_recent_published(self, limit: int = 20) -> list[dict]:
        try:
            pool = await asyncpg.create_pool(
                self.url, min_size=1, max_size=2,
                command_timeout=15, ssl="require",
            )
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT id, title, raw_text, url, published
                       FROM articles
                       WHERE status = 'published'
                       ORDER BY fetched_at DESC
                       LIMIT $1""",
                    limit,
                )
            await pool.close()
            result = [dict(r) for r in rows]
            logger.info(f"NewsReader: получено {len(result)} опубликованных статей")
            return result
        except Exception as e:
            logger.error(f"Ошибка чтения новостей из БД: {e}")
            return []
