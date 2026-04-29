"""
video/backgrounds.py — Скачивание фоновых видео с Pexels
"""
import asyncio
import os
import random
from pathlib import Path
import aiohttp
import aiofiles
from loguru import logger

PEXELS_KEY  = os.getenv("PEXELS_API_KEY", "")
BG_DIR      = "/app/backgrounds"
PEXELS_URL  = "https://api.pexels.com/videos/search"

# Запросы для фоновых видео — абстрактные, подходят к финансовым новостям
SEARCH_QUERIES = [
    "city night timelapse",
    "stock market trading",
    "money finance abstract",
    "city traffic aerial",
    "technology digital abstract",
    "skyscraper business",
    "new york city aerial",
    "crypto blockchain abstract",
]


async def download_background(query: str, output_path: str) -> bool:
    """Скачивает одно вертикальное видео с Pexels."""
    if not PEXELS_KEY:
        logger.warning("PEXELS_API_KEY не задан — используем градиентный фон")
        return False

    headers = {"Authorization": PEXELS_KEY}
    params  = {"query": query, "per_page": 10, "orientation": "portrait"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(PEXELS_URL, headers=headers, params=params,
                                   timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    logger.warning(f"Pexels API ответил {resp.status}")
                    return False
                data = await resp.json()

            videos = data.get("videos", [])
            if not videos:
                logger.warning(f"Pexels: нет видео для '{query}'")
                return False

            # Берём случайное видео из результатов
            video = random.choice(videos[:5])

            # Ищем файл с наименьшим разрешением (быстрее скачать)
            files = sorted(
                video.get("video_files", []),
                key=lambda f: f.get("width", 9999)
            )
            # Предпочитаем вертикальные файлы
            vertical = [f for f in files if f.get("width", 0) < f.get("height", 0)]
            chosen = vertical[0] if vertical else files[0]

            video_url = chosen["link"]
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)

            async with session.get(video_url, timeout=aiohttp.ClientTimeout(total=60)) as r:
                if r.status != 200:
                    return False
                async with aiofiles.open(output_path, "wb") as f:
                    async for chunk in r.content.iter_chunked(1024 * 64):
                        await f.write(chunk)

        logger.info(f"Фон скачан: {Path(output_path).name}")
        return True

    except Exception as e:
        logger.error(f"Ошибка скачивания фона: {e}")
        return False


async def get_background(reel_id: int) -> str | None:
    """
    Возвращает путь к фоновому видео.
    Сначала проверяет кэш, потом скачивает новый.
    """
    Path(BG_DIR).mkdir(parents=True, exist_ok=True)

    # Проверяем кэшированные фоны
    cached = list(Path(BG_DIR).glob("*.mp4"))
    if cached and len(cached) >= 3:
        chosen = random.choice(cached)
        logger.debug(f"Используем кэшированный фон: {chosen.name}")
        return str(chosen)

    # Скачиваем новый
    query = random.choice(SEARCH_QUERIES)
    idx   = len(cached) + 1
    path  = f"{BG_DIR}/bg_{idx:03d}.mp4"

    success = await download_background(query, path)
    if success:
        return path

    # Если Pexels недоступен — вернём None (будет градиентный фон)
    return None
