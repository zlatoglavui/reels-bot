"""
pipeline.py — Главный оркестратор
новость → сценарий → аудио → видео → отправить в Telegram
"""
import asyncio
import os
from datetime import datetime
from pathlib import Path
from loguru import logger

from src.storage.database import ReelsDatabase, NewsReader
from src.selector.selector import select_for_reels
from src.script.generator import ScriptGenerator
from src.tts.synthesizer import synthesize
from src.video.backgrounds import get_background
from src.video.composer import compose_video
from src.telegram_sender import TelegramSender

OUTPUT_DIR     = os.getenv("OUTPUT_DIR", "/app/output")
VIDEOS_PER_DAY = int(os.getenv("VIDEOS_PER_DAY", "8"))


class ReelsPipeline:
    def __init__(self):
        self.db        = ReelsDatabase()
        self.news      = NewsReader()
        self.generator = ScriptGenerator()
        self.sender    = TelegramSender()

    async def startup(self):
        Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
        Path("/app/backgrounds").mkdir(parents=True, exist_ok=True)
        Path("/app/audio").mkdir(parents=True, exist_ok=True)
        await self.db.connect()
        logger.info("Reels Pipeline запущен ✓")

    async def shutdown(self):
        await self.db.close()

    async def process_one(self, article: dict) -> bool:
        """Полный цикл для одной статьи."""
        article_id = article.get("id")
        title      = article.get("title", "")[:80]
        ts         = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        safe_title = "".join(c if c.isalnum() else "_" for c in title[:30])

        audio_path = f"/app/audio/{ts}_{safe_title}.mp3"
        video_path = f"{OUTPUT_DIR}/{ts}_{safe_title}.mp4"

        reel_id = await self.db.create_reel(article_id, title)
        logger.info(f"▶ Обрабатываем: {title[:60]}")

        # ── Шаг 1: Сценарий ───────────────────────────────────
        script = await self.generator.generate(article)
        if not script:
            await self.db.update_reel(reel_id, status="error", error_msg="script failed")
            return False

        await self.db.update_reel(reel_id, script=script["full_text"])
        logger.info(f"  Хук: {script['hook'][:60]}")

        # ── Шаг 2: Озвучка ────────────────────────────────────
        duration = await synthesize(script["full_text"], audio_path)
        if not duration:
            await self.db.update_reel(reel_id, status="error", error_msg="tts failed")
            return False

        duration = min(duration, 30.0)
        await self.db.update_reel(reel_id, audio_path=audio_path, status="audio_done")

        # ── Шаг 3: Фон ────────────────────────────────────────
        background = await get_background(reel_id)

        # ── Шаг 4: Видео ──────────────────────────────────────
        success = await compose_video(
            background_path=background,
            audio_path=audio_path,
            script=script,
            output_path=video_path,
            duration=duration,
        )

        if not success:
            await self.db.update_reel(reel_id, status="error", error_msg="ffmpeg failed")
            return False

        await self.db.update_reel(reel_id, video_path=video_path, status="done")
        logger.info(f"  ✅ Видео готово: {Path(video_path).name}")

        # ── Шаг 5: Отправка в Telegram ────────────────────────
        caption = (
            f"🎬 {script['hook']}\n\n"
            f"📰 {title[:100]}\n\n"
            f"#reels #финансы"
        )
        await self.sender.send_video(video_path, caption=caption)

        return True

    async def run_once(self):
        start = datetime.utcnow()
        logger.info("─" * 40)
        logger.info(f"Старт цикла: {start.strftime('%Y-%m-%d %H:%M:%S')} UTC")

        today_count = await self.db.count_today()
        if today_count >= VIDEOS_PER_DAY:
            logger.info(f"Дневной лимит {VIDEOS_PER_DAY} видео достигнут")
            return

        remaining = VIDEOS_PER_DAY - today_count

        articles = await self.news.get_recent_published(limit=30)
        if not articles:
            logger.info("Нет опубликованных новостей для обработки")
            return

        new_articles = []
        for a in articles:
            if not await self.db.reel_exists(a["id"]):
                new_articles.append(a)

        if not new_articles:
            logger.info("Все новости уже обработаны")
            return

        selected = select_for_reels(new_articles, max_count=min(remaining, 3))

        stats = {"success": 0, "error": 0}
        for article in selected:
            try:
                ok = await self.process_one(article)
                stats["success" if ok else "error"] += 1
                await asyncio.sleep(5)
            except Exception as e:
                logger.exception(f"Ошибка обработки: {e}")
                stats["error"] += 1

        elapsed = (datetime.utcnow() - start).total_seconds()
        logger.info(
            f"Цикл завершён за {elapsed:.0f}с | "
            f"создано={stats['success']} ошибок={stats['error']} "
            f"видео сегодня={today_count + stats['success']}/{VIDEOS_PER_DAY}"
        )
