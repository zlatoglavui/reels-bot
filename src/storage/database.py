"""
storage/database.py — Читает опубликованные новости из БД новостного бота
и ведёт собственный учёт сгенерированных видео
"""
import os
from datetime import datetime
from typing import Optional
import aiosqlite
from loguru import logger

NEWS_DB   = os.getenv("NEWS_DB_PATH", "/app/data/finews.db")
REELS_DB  = os.getenv("REELS_DB_PATH", "/app/output/reels.db")

CREATE_REELS_TABLES = """
CREATE TABLE IF NOT EXISTS reels (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id   INTEGER,
    title        TEXT,
    script       TEXT,
    audio_path   TEXT,
    video_path   TEXT,
    status       TEXT DEFAULT 'pending',
    -- pending | audio_done | video_done | done | error
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    error_msg    TEXT
);
CREATE INDEX IF NOT EXISTS idx_reels_status ON reels(status);
CREATE INDEX IF NOT EXISTS idx_reels_article ON reels(article_id);
"""


class ReelsDatabase:
    def __init__(self):
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self):
        os.makedirs(os.path.dirname(REELS_DB), exist_ok=True)
        self._conn = await aiosqlite.connect(REELS_DB)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(CREATE_REELS_TABLES)
        await self._conn.commit()
        logger.info(f"Reels БД подключена: {REELS_DB}")

    async def close(self):
        if self._conn:
            await self._conn.close()

    async def reel_exists(self, article_id: int) -> bool:
        async with self._conn.execute(
            "SELECT 1 FROM reels WHERE article_id = ?", (article_id,)
        ) as cur:
            return await cur.fetchone() is not None

    async def create_reel(self, article_id: int, title: str) -> int:
        async with self._conn.execute(
            "INSERT INTO reels (article_id, title) VALUES (?, ?)",
            (article_id, title),
        ) as cur:
            await self._conn.commit()
            return cur.lastrowid

    async def update_reel(self, reel_id: int, **kwargs):
        if not kwargs:
            return
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values()) + [reel_id]
        await self._conn.execute(
            f"UPDATE reels SET {sets} WHERE id = ?", vals
        )
        await self._conn.commit()

    async def count_today(self) -> int:
        async with self._conn.execute(
            "SELECT COUNT(*) as cnt FROM reels WHERE date(created_at) = date('now') AND status = 'done'"
        ) as cur:
            row = await cur.fetchone()
            return row["cnt"] if row else 0


class NewsReader:
    """Читает опубликованные статьи из БД новостного бота."""

    async def get_recent_published(self, limit: int = 20) -> list[dict]:
        """Возвращает последние опубликованные статьи."""
        try:
            async with aiosqlite.connect(NEWS_DB) as conn:
                conn.row_factory = aiosqlite.Row
                async with conn.execute(
                    """SELECT id, title, raw_text, url, published
                       FROM articles
                       WHERE status = 'published'
                       ORDER BY fetched_at DESC
                       LIMIT ?""",
                    (limit,),
                ) as cur:
                    rows = await cur.fetchall()
                    return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Ошибка чтения news БД: {e}")
            return []
