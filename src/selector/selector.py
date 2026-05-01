"""
selector/selector.py — Отбирает новости подходящие для видео-роликов
"""
import re
from loguru import logger

# Темы которые хорошо заходят в видео формате
STRONG_KEYWORDS = [
    # Крипта
    "bitcoin", "ethereum", "crypto", "биткоин", "крипта", "btc", "eth",
    # Макро
    "inflation", "инфляция", "fed", "rate", "ставка", "recession", "рецессия",
    # Рынки
    "market crash", "обвал", "rally", "рост рынка", "stock", "акции",
    # Деньги/экономика
    "dollar", "доллар", "oil", "нефть", "gdp", "ввп", "unemployment",
    # Громкие события
    "billion", "миллиард", "trillion", "триллион", "record", "рекорд",
    "crisis", "кризис", "collapse", "крах", "surge", "взлет",
]

# Слабые темы — не подходят для коротких видео
WEAK_KEYWORDS = [
    "opinion", "мнение", "review", "обзор продукта", "partnership",
    "sponsor", "sponsored", "реклама", "pr ", "press release",
    "annual report", "quarterly report", "earnings call transcript",
]

# Минимальная длина текста для генерации видео
MIN_TEXT_LENGTH = 50


def _normalize(text: str) -> str:
    return text.lower()


def score_article(article: dict) -> int:
    """Возвращает score статьи. >0 — подходит для видео."""
    title = _normalize(article.get("title", ""))
    text  = _normalize(article.get("raw_text", ""))
    full  = f"{title} {text}"

    # Отсекаем слабые
    for kw in WEAK_KEYWORDS:
        if kw in full:
            return -1

    # Слишком короткий текст
    if len(article.get("raw_text", "")) < MIN_TEXT_LENGTH:
        return 0

    # Считаем сильные ключевые слова
    score = sum(1 for kw in STRONG_KEYWORDS if kw in full)

    # Бонус за числа и проценты — значит есть конкретика
    if re.search(r'\d+[\.,]\d+%?|\$[\d,]+', full):
        score += 2

    return score


def select_for_reels(articles: list[dict], max_count: int = 5) -> list[dict]:
    """Отбирает лучшие статьи для генерации видео."""
    scored = []
    for a in articles:
        s = score_article(a)
        if s >= 0:
            scored.append((s, a))

    # Сортируем по score убыванию
    scored.sort(key=lambda x: x[0], reverse=True)
    selected = [a for _, a in scored[:max_count]]

    logger.info(
        f"Селектор: {len(selected)} выбрано из {len(articles)} "
        f"(отфильтровано {len(articles) - len(selected)})"
    )
    return selected
