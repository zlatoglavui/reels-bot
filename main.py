"""
main.py — Reels Bot entry point (Railway-ready)
новость → сценарий → аудио → видео → сохранить
"""
import asyncio
import os
import signal
import sys
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

# Создаём папки при старте
for d in ["/app/output", "/app/audio", "/app/backgrounds"]:
    Path(d).mkdir(parents=True, exist_ok=True)

# Логирование
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logger.remove()
logger.add(
    sys.stdout,
    level=LOG_LEVEL,
    colorize=False,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {message}",
)
logger.add(
    "/app/output/reels.log",
    level="DEBUG",
    rotation="10 MB",
    retention="14 days",
)

# Проверка переменных
REQUIRED = ["GROQ_API_KEY", "PEXELS_API_KEY"]
missing = [v for v in REQUIRED if not os.getenv(v)]
if missing:
    logger.error(f"Отсутствуют переменные: {missing}")
    logger.error("Добавь в Railway → Variables")
    sys.exit(1)

from src.pipeline import ReelsPipeline


async def main():
    logger.info("=" * 50)
    logger.info("Reels Bot стартует...")
    logger.info("=" * 50)

    pipeline = ReelsPipeline()
    await pipeline.startup()

    interval = int(os.getenv("INTERVAL_MINUTES", "60"))
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        pipeline.run_once,
        trigger=IntervalTrigger(minutes=interval),
        id="reels_pipeline",
        max_instances=1,
        replace_existing=True,
        misfire_grace_time=120,
    )
    scheduler.start()
    logger.info(f"Планировщик запущен — каждые {interval} минут")

    # Первый запуск сразу
    await pipeline.run_once()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    await stop_event.wait()
    scheduler.shutdown(wait=False)
    await pipeline.shutdown()
    logger.info("Reels Bot остановлен")


if __name__ == "__main__":
    asyncio.run(main())
