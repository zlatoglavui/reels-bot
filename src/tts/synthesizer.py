"""
tts/synthesizer.py — Генерация озвучки через Edge TTS (бесплатно, Microsoft)
Голоса: ru-RU-DmitryNeural (мужской), ru-RU-SvetlanaNeural (женский)
"""
import asyncio
import os
from pathlib import Path
import edge_tts
from mutagen.mp3 import MP3
from loguru import logger

VOICE    = os.getenv("TTS_VOICE", "ru-RU-DmitryNeural")
RATE     = os.getenv("TTS_RATE", "+10%")   # скорость речи
VOLUME   = "+0%"


async def synthesize(text: str, output_path: str) -> float | None:
    """
    Генерирует MP3 из текста.
    Возвращает длительность в секундах или None при ошибке.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    communicate = edge_tts.Communicate(
        text=text,
        voice=VOICE,
        rate=RATE,
        volume=VOLUME,
    )

    try:
        await communicate.save(output_path)
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
        return 20.0  # fallback


async def list_russian_voices():
    """Выводит список доступных русских голосов."""
    voices = await edge_tts.list_voices()
    ru_voices = [v for v in voices if v["Locale"].startswith("ru")]
    for v in ru_voices:
        print(f"{v['ShortName']} — {v['Gender']}")
    return ru_voices
