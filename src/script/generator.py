"""
script/generator.py — Генерация сценария для видео через Groq
"""
import os
import re
from groq import AsyncGroq
from loguru import logger

SYSTEM_PROMPT = """Ты создаёшь короткие вирусные сценарии для TikTok/Reels на финансовую тему.

Твоя задача — написать сценарий на 15–20 секунд (40–55 слов) на русском языке.

СТРОГО верни только этот формат без лишних слов:

ХУК: [1 цепляющая строка — заставляет остановить скролл, упомяни деньги или угрозу]
СУТЬ: [2–3 коротких предложения — главный факт с цифрами]
ВЫВОД: [1 строка — что делать зрителю прямо сейчас]

Правила:
- Говори как живой человек, не как робот
- Используй "ты", "твои деньги", "прямо сейчас"
- Конкретные цифры если есть
- Эмоциональный но не кликбейтный тон
- Максимум 55 слов суммарно"""


def parse_script(raw: str) -> dict | None:
    """Парсит ответ LLM в структурированный сценарий."""
    lines = raw.strip().split("\n")
    result = {"hook": "", "body": "", "conclusion": ""}

    for line in lines:
        line = line.strip()
        if not line:
            continue
        low = line.lower()
        if low.startswith("хук:") or low.startswith("hook:"):
            result["hook"] = re.sub(r'^[хХhH][уУuU][кК][:\s]*', '', line, flags=re.IGNORECASE).strip()
        elif low.startswith("суть:") or low.startswith("body:"):
            result["body"] = re.sub(r'^[сС][уУ][тТ][ьЬ][:\s]*', '', line, flags=re.IGNORECASE).strip()
        elif low.startswith("вывод:") or low.startswith("conclusion:"):
            result["conclusion"] = re.sub(r'^[вВ][ыЫ][вВ][оО][дД][:\s]*', '', line, flags=re.IGNORECASE).strip()

    # Если парсинг не удался — берём строки по порядку
    non_empty = [l.strip() for l in lines if l.strip()]
    if not result["hook"] and len(non_empty) >= 1:
        result["hook"] = non_empty[0]
    if not result["body"] and len(non_empty) >= 2:
        result["body"] = " ".join(non_empty[1:-1]) if len(non_empty) > 2 else non_empty[1]
    if not result["conclusion"] and len(non_empty) >= 2:
        result["conclusion"] = non_empty[-1]

    if not result["hook"]:
        return None

    # Полный текст для TTS
    result["full_text"] = f"{result['hook']} {result['body']} {result['conclusion']}".strip()
    return result


class ScriptGenerator:
    def __init__(self):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY не задан")
        self.client = AsyncGroq(api_key=api_key)
        self.model = "llama-3.3-70b-versatile"  # Более умная модель для сценариев

    async def generate(self, article: dict) -> dict | None:
        title = article.get("title", "")
        text  = article.get("raw_text", "")[:2000]

        user_content = f"Заголовок: {title}\nТекст: {text}"

        for attempt in range(3):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user",   "content": user_content},
                    ],
                    max_tokens=200,
                    temperature=0.7,
                )
                raw = response.choices[0].message.content
                script = parse_script(raw)

                if script:
                    logger.info(f"Сценарий готов: {title[:50]}")
                    logger.debug(f"Хук: {script['hook']}")
                    return script

                logger.warning(f"Не удалось распарсить сценарий (попытка {attempt+1})")

            except Exception as e:
                err = str(e)
                if "429" in err or "rate" in err.lower():
                    logger.warning("Groq rate limit при генерации сценария")
                    import asyncio; await asyncio.sleep(30)
                else:
                    logger.error(f"Ошибка генерации сценария: {err[:100]}")
                    if attempt == 2:
                        return None

        return None
