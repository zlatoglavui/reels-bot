"""
video/backgrounds.py — Умный подбор фонов по теме новости
"""
import os
import random
from pathlib import Path
import aiohttp
import aiofiles
from loguru import logger

PEXELS_KEY = os.getenv("PEXELS_API_KEY", "")
BG_DIR     = "/app/backgrounds"
PEXELS_URL = "https://api.pexels.com/videos/search"

# Тематические фоны по ключевым словам новости
TOPIC_QUERIES = {
    "crypto":      ["bitcoin cryptocurrency", "crypto trading screen", "blockchain technology"],
    "bitcoin":     ["bitcoin cryptocurrency", "crypto coin gold"],
    "ethereum":    ["ethereum crypto", "blockchain digital"],
    "oil":         ["oil refinery", "petroleum industry", "oil barrels"],
    "gold":        ["gold bars", "precious metals", "gold investment"],
    "fed":         ["federal reserve building", "central bank", "wall street"],
    "inflation":   ["shopping prices", "money inflation", "economic crisis"],
    "stocks":      ["stock market chart", "wall street trading", "nasdaq screen"],
    "dollar":      ["dollar bills", "currency exchange", "usd money"],
    "market":      ["stock market trading", "financial charts", "wall street"],
    "recession":   ["economic crisis", "financial market crash", "business decline"],
    "rate":        ["federal reserve", "interest rate", "banking finance"],
    "earnings":    ["business earnings", "corporate finance", "stock market"],
    "default":     ["city night timelapse", "skyscraper business", "financial district"],
}

def get_query_for_article(article: dict) -> str:
    """Выбирает поисковый запрос Pexels исходя из темы статьи."""
    text = f"{article.get('title', '')} {article.get('raw_text', '')}".lower()
    for keyword, queries in TOPIC_QUERIES.items():
        if keyword in text:
            return random.choice(queries)
    return random.choice(TOPIC_QUERIES["default"])


async def download_background(query: str, output_path: str) -> bool:
    if not PEXELS_KEY:
        logger.warning("PEXELS_API_KEY не задан — градиентный фон")
        return False

    headers = {"Authorization": PEXELS_KEY}
    params  = {"query": query, "per_page": 15, "orientation": "portrait"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                PEXELS_URL, headers=headers, params=params,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"Pexels {resp.status} для '{query}'")
                    return False
                data = await resp.json()

            videos = data.get("videos", [])
            if not videos:
                logger.warning(f"Pexels: нет видео для '{query}'")
                return False

            # Берём случайное из первых 5
            video = random.choice(videos[:5])
            files = video.get("video_files", [])

            # Предпочитаем вертикальные файлы
            vertical = [f for f in files if f.get("width", 0) < f.get("height", 0)]
            pool     = vertical if vertical else files
            # Берём файл со средним качеством — не самый маленький и не самый большой
            pool_sorted = sorted(pool, key=lambda f: f.get("width", 0))
            chosen = pool_sorted[len(pool_sorted) // 2] if len(pool_sorted) > 1 else pool_sorted[0]

            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            async with session.get(
                chosen["link"], timeout=aiohttp.ClientTimeout(total=60)
            ) as r:
                if r.status != 200:
                    return False
                async with aiofiles.open(output_path, "wb") as f:
                    async for chunk in r.content.iter_chunked(1024 * 64):
                        await f.write(chunk)

        logger.info(f"Фон скачан: {Path(output_path).name} (запрос: {query})")
        return True

    except Exception as e:
        logger.error(f"Ошибка скачивания фона: {e}")
        return False


async def get_background(reel_id: int, article: dict = None) -> str | None:
    Path(BG_DIR).mkdir(parents=True, exist_ok=True)

    # Для каждого видео скачиваем свежий тематический фон
    query = get_query_for_article(article) if article else random.choice(TOPIC_QUERIES["default"])
    path  = f"{BG_DIR}/bg_{reel_id:04d}.mp4"

    # Если файл уже есть — используем
    if Path(path).exists():
        return path

    success = await download_background(query, path)
    return path if success else None
