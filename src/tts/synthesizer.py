"""
tts/synthesizer.py — Google TTS (gTTS)
Работает на облачных серверах, бесплатно, без API ключа
"""
import asyncio
import os
from pathlib import Path
from gtts import gTTS
from mutagen.mp3 import MP3
from loguru import logger

LANG  = os.getenv("TTS_LANG", "ru")
SLOW  = os.getenv("TTS_SLOW", "false").lower() == "true"


def _synthesize_sync(text: str, output_path: str):
    """Синхронная генерация MP3 через gTTS."""
    tts = gTTS(text=text, lang=LANG, slow=SLOW)
    tts.save(output_path)


async def synthesize(text: str, output_path: str) -> float | None:
    """
    Генерирует MP3 из текста через Google TTS.
    Возвращает длительность в секундах или None при ошибке.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    try:
        # gTTS синхронный — запускаем в executor
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, _synthesize_sync, text, output_path
        )
        duration = get_audio_duration(output_path)
        logger.info(f"TTS готов: {Path(output_path).name} ({duration:.1f}с)")
        return duration

    except Exception as e:
        logger.error(f"TTS ошибка: {e}")
        return None


def get_audio_duration(path: str) -> float:
    """Возвращает длительность MP3 в секундах."""
    try:
        audio = MP3(path)
        return audio.info.length
    except Exception:
        return 20.0
