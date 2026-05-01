"""
script/generator.py — Генерация сценария для TikTok/Reels через Groq
Оптимизировано для перегона трафика в Telegram
"""
import os
import re
import random
from groq import AsyncGroq
from loguru import logger

# 6 разных типов хуков — чередуются чтобы не приедались
HOOK_STYLES = [
    "Начни с шокирующего факта с цифрой — например '${сумма} испарилось за час'",
    "Начни с вопроса который задевает — например 'Ты знаешь куда уходят твои сбережения?'",
    "Начни с предупреждения — например 'Стоп. Это касается каждого кто держит доллары'",
    "Начни с интриги — например 'То что скрывают банки от обычных людей'",
    "Начни с противоречия — например 'Все паникуют. А умные деньги делают вот что'",
    "Начни с новости напрямую — например 'Только что произошло то что изменит рынок'",
]

SYSTEM_PROMPT = """Ты создаёшь короткие вирусные сценарии для TikTok и Reels на финансовую тему.
Главная цель — заинтересовать зрителя и отправить его в Telegram канал за подробностями.

Твоя задача — написать сценарий ровно на 15 секунд (35-40 слов) на русском языке.

СТРОГО верни только этот формат:

ХУК: [1 цепляющая строка]
СУТЬ: [1-2 предложения с главным фактом и цифрами]
ВЫВОД: [1 строка с призывом — заканчивай на "подробности в Telegram — ссылка в шапке профиля"]

Правила:
- Говори как живой человек с эмоцией
- Используй "ты", "твои деньги"
- Конкретные цифры если есть в тексте
- Динамичный темп — короткие предложения
- Максимум 40 слов суммарно — это критично для 15 секунд
- {hook_style}"""

CTA_PHRASES = [
    "Все детали в Telegram — ссылка в шапке профиля",
    "Подробный разбор в Telegram канале — там в шапке",
    "Больше таких разборов каждый день в Telegram — ссылка в шапке",
    "Следи за рынком вместе с нами — Telegram в шапке профиля",
]


def parse_script(raw: str) -> dict | None:
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

    non_empty = [l.strip() for l in lines if l.strip()]
    if not result["hook"] and len(non_empty) >= 1:
        result["hook"] = non_empty[0]
    if not result["body"] and len(non_empty) >= 2:
        result["body"] = " ".join(non_empty[1:-1]) if len(non_empty) > 2 else non_empty[1]
    if not result["conclusion"] and len(non_empty) >= 2:
        result["conclusion"] = non_empty[-1]

    if not result["hook"]:
        return None

    # Добавляем CTA если его нет в выводе
    cta = random.choice(CTA_PHRASES)
    conclusion = result["conclusion"]
    if "telegram" not in conclusion.lower() and "шапк" not in conclusion.lower():
        conclusion = cta
    result["conclusion"] = conclusion

    result["full_text"] = f"{result['hook']} {result['body']} {conclusion}".strip()
    return result


class ScriptGenerator:
    def __init__(self):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY не задан")
        self.client = AsyncGroq(api_key=api_key)
        self.model  = "llama-3.3-70b-versatile"
        self._hook_idx = 0  # ротация хуков по порядку

    def _next_hook_style(self) -> str:
        style = HOOK_STYLES[self._hook_idx % len(HOOK_STYLES)]
        self._hook_idx += 1
        return style

    async def generate(self, article: dict) -> dict | None:
        title = article.get("title", "")
        text  = article.get("raw_text", "")[:2000]

        hook_style = self._next_hook_style()
        prompt = SYSTEM_PROMPT.replace("{hook_style}", hook_style)

        user_content = f"Заголовок: {title}\nТекст: {text}"

        for attempt in range(3):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user",   "content": user_content},
                    ],
                    max_tokens=150,
                    temperature=0.8,
                )
                raw    = response.choices[0].message.content
                script = parse_script(raw)

                if script:
                    logger.info(f"Сценарий готов: {title[:50]}")
                    logger.info(f"  Хук: {script['hook']}")
                    return script

                logger.warning(f"Не удалось распарсить (попытка {attempt+1})")

            except Exception as e:
                err = str(e)
                if "429" in err or "rate" in err.lower():
                    logger.warning("Groq rate limit")
                    import asyncio; await asyncio.sleep(30)
                else:
                    logger.error(f"Ошибка генерации: {err[:100]}")
                    if attempt == 2:
                        return None

        return None
