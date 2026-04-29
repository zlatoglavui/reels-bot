"""
video/composer.py — Сборка финального видео через FFmpeg
Формат: 1080x1920 (9:16 вертикальный)
"""
import asyncio
import os
import re
import textwrap
from pathlib import Path
from loguru import logger

WIDTH  = 1080
HEIGHT = 1920
FONT   = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_FALLBACK = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/app/output")


def get_font() -> str:
    for f in [FONT, FONT_FALLBACK]:
        if os.path.exists(f):
            return f
    return "DejaVuSans-Bold"  # системный fallback


def split_into_phrases(text: str, words_per_phrase: int = 4) -> list[str]:
    """Разбивает текст на фразы по N слов для субтитров."""
    words = text.split()
    phrases = []
    for i in range(0, len(words), words_per_phrase):
        phrase = " ".join(words[i:i + words_per_phrase])
        phrases.append(phrase)
    return phrases


def build_subtitle_filter(phrases: list[str], total_duration: float) -> str:
    """
    Строит FFmpeg drawtext фильтр для субтитров.
    Каждая фраза показывается равное время.
    """
    if not phrases:
        return "null"

    font = get_font()
    time_per_phrase = total_duration / len(phrases)
    filters = []

    for i, phrase in enumerate(phrases):
        start = i * time_per_phrase
        end   = start + time_per_phrase

        # Экранируем спецсимволы для FFmpeg
        safe = (phrase
                .replace("'", "\\'")
                .replace(":", "\\:")
                .replace(",", "\\,")
                .replace("[", "\\[")
                .replace("]", "\\]"))

        # Белый текст с чёрной тенью — читается на любом фоне
        f = (
            f"drawtext=fontfile='{font}'"
            f":text='{safe}'"
            f":fontsize=72"
            f":fontcolor=white"
            f":shadowcolor=black@0.8"
            f":shadowx=3:shadowy=3"
            f":x=(w-text_w)/2"
            f":y=(h-text_h)/2+200"
            f":enable='between(t,{start:.2f},{end:.2f})'"
        )
        filters.append(f)

    return ",".join(filters)


async def run_ffmpeg(cmd: list[str]) -> bool:
    """Запускает FFmpeg команду асинхронно."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        logger.error(f"FFmpeg ошибка: {stderr.decode()[-500:]}")
        return False
    return True


async def create_gradient_background(duration: float, output_path: str) -> bool:
    """Создаёт градиентный фон если Pexels недоступен."""
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        # Тёмно-синий → фиолетовый градиент
        "-i", f"color=c=0x0a0a2e:size={WIDTH}x{HEIGHT}:rate=30:duration={duration}",
        "-vf", (
            f"drawbox=x=0:y=0:w={WIDTH}:h={HEIGHT//2}:"
            f"color=0x1a1a4e@0.5:t=fill"
        ),
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-t", str(duration),
        output_path
    ]
    return await run_ffmpeg(cmd)


async def compose_video(
    background_path: str | None,
    audio_path: str,
    script: dict,
    output_path: str,
    duration: float,
) -> bool:
    """
    Собирает финальное видео:
    фон + субтитры (хук + суть + вывод) + аудио
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    font      = get_font()
    phrases   = split_into_phrases(script.get("full_text", ""), words_per_phrase=4)
    sub_filter = build_subtitle_filter(phrases, duration)

    # Экранируем заголовок для отображения вверху
    hook = (script.get("hook", "")
            .replace("'", "\\'")
            .replace(":", "\\:")
            .replace(",", "\\,"))

    # Тёмный оверлей для читаемости текста
    overlay = f"drawbox=x=0:y=0:w={WIDTH}:h={HEIGHT}:color=black@0.45:t=fill"

    # Хук вверху экрана
    hook_filter = (
        f"drawtext=fontfile='{font}'"
        f":text='{hook}'"
        f":fontsize=56"
        f":fontcolor=yellow"
        f":shadowcolor=black@0.9"
        f":shadowx=2:shadowy=2"
        f":x=(w-text_w)/2"
        f":y=180"
        f":enable='between(t,0,{duration:.2f})'"
    )

    # Логотип/водяной знак внизу
    watermark = (
        f"drawtext=fontfile='{font}'"
        f":text='@propustilnews'"
        f":fontsize=36"
        f":fontcolor=white@0.6"
        f":x=(w-text_w)/2"
        f":y={HEIGHT - 120}"
    )

    full_vf = f"{overlay},{hook_filter},{sub_filter},{watermark}"

    if background_path and os.path.exists(background_path):
        # С фоновым видео
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1",       # зацикливаем фон
            "-i", background_path,
            "-i", audio_path,
            "-vf", (
                f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
                f"crop={WIDTH}:{HEIGHT},"
                f"{full_vf}"
            ),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-t", str(duration),
            "-shortest",
            "-movflags", "+faststart",
            output_path,
        ]
    else:
        # С градиентным фоном
        tmp_bg = output_path.replace(".mp4", "_bg.mp4")
        await create_gradient_background(duration, tmp_bg)

        cmd = [
            "ffmpeg", "-y",
            "-i", tmp_bg,
            "-i", audio_path,
            "-vf", full_vf,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-t", str(duration),
            "-shortest",
            "-movflags", "+faststart",
            output_path,
        ]

    success = await run_ffmpeg(cmd)

    # Удаляем временный фон
    tmp = output_path.replace(".mp4", "_bg.mp4")
    if os.path.exists(tmp):
        os.remove(tmp)

    if success:
        size_mb = os.path.getsize(output_path) / 1024 / 1024
        logger.info(f"Видео готово: {Path(output_path).name} ({size_mb:.1f} MB, {duration:.1f}с)")

    return success
