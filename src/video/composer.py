"""
video/composer.py — Сборка видео через FFmpeg (высокое качество)
"""
import asyncio
import os
import random
from pathlib import Path
from loguru import logger

WIDTH  = 1080
HEIGHT = 1920
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/app/output")
MUSIC_DIR  = "/app/music"


def split_into_phrases(text: str, words_per_phrase: int = 4) -> list[str]:
    words = text.split()
    return [
        " ".join(words[i:i + words_per_phrase])
        for i in range(0, len(words), words_per_phrase)
    ]


def clean_text(text: str) -> str:
    allowed = set(
        "абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "0123456789 .-+"
    )
    return "".join(c for c in text if c in allowed).strip()


def get_music_file() -> str | None:
    music_dir = Path(MUSIC_DIR)
    if not music_dir.exists():
        return None
    tracks = list(music_dir.glob("*.mp3"))
    if not tracks:
        return None
    track = str(random.choice(tracks))
    try:
        from mutagen.mp3 import MP3
        if MP3(track).info.length < 5.0:
            return None
    except Exception:
        return None
    return track


async def download_music():
    music_dir = Path(MUSIC_DIR)
    music_dir.mkdir(parents=True, exist_ok=True)
    tracks = [
        ("https://cdn.pixabay.com/download/audio/2022/01/18/audio_d0c6ff1bab.mp3", "ambient1.mp3"),
        ("https://cdn.pixabay.com/download/audio/2022/03/10/audio_c8c8a73467.mp3", "ambient2.mp3"),
        ("https://cdn.pixabay.com/download/audio/2021/11/01/audio_cb417e5bb4.mp3", "ambient3.mp3"),
    ]
    import aiohttp
    for url, name in tracks:
        path = music_dir / name
        if path.exists():
            continue
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(url, timeout=aiohttp.ClientTimeout(total=30)) as r:
                    if r.status == 200:
                        path.write_bytes(await r.read())
                        logger.info(f"Музыка скачана: {name}")
        except Exception as e:
            logger.warning(f"Музыка {name} недоступна: {e}")


async def run_ffmpeg(cmd: list[str], label: str = "") -> bool:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        err = stderr.decode(errors="replace")
        logger.error(f"FFmpeg [{label}] ошибка: {err[-300:]}")
        return False
    return True


async def make_background(duration: float, output_path: str) -> bool:
    """Тёмный градиентный фон."""
    return await run_ffmpeg([
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c=0x0d0d1a:size={WIDTH}x{HEIGHT}:rate=30",
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p",
        output_path,
    ], "background")


async def compose_video(
    background_path: str | None,
    audio_path: str,
    script: dict,
    output_path: str,
    duration: float,
) -> bool:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    music = get_music_file()

    # Шаг 1: фон
    tmp_bg = output_path.replace(".mp4", "_bg.mp4")
    bg_ok  = False

    if background_path and os.path.exists(background_path):
        bg_ok = await run_ffmpeg([
            "ffmpeg", "-y",
            "-i", background_path,
            "-vf", (
                f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
                f"crop={WIDTH}:{HEIGHT}"
            ),
            "-t", str(duration),
            "-r", "30",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-an",
            tmp_bg,
        ], "bg_transcode")

    if not bg_ok:
        logger.info("Используем градиентный фон")
        bg_ok = await make_background(duration, tmp_bg)

    if not bg_ok:
        logger.error("Не удалось создать фон")
        return False

    # Шаг 2: субтитры через SRT
    srt_path = output_path.replace(".mp4", ".srt")
    phrases  = split_into_phrases(script.get("full_text", ""), words_per_phrase=4)
    time_per = duration / max(len(phrases), 1)

    def fmt_time(s: float) -> str:
        h   = int(s // 3600)
        m   = int((s % 3600) // 60)
        sec = s % 60
        return f"{h:02d}:{m:02d}:{sec:06.3f}".replace(".", ",")

    srt_lines = []
    for i, phrase in enumerate(phrases):
        safe = clean_text(phrase)
        if not safe:
            continue
        srt_lines += [
            str(i + 1),
            f"{fmt_time(i * time_per)} --> {fmt_time((i + 1) * time_per)}",
            safe,
            "",
        ]

    with open(srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(srt_lines))

    tmp_txt = output_path.replace(".mp4", "_txt.mp4")
    subtitle_ok = await run_ffmpeg([
        "ffmpeg", "-y",
        "-i", tmp_bg,
        "-vf", (
            f"subtitles={srt_path}:force_style='"
            f"FontSize=52,"
            f"PrimaryColour=&Hffffff,"
            f"OutlineColour=&H000000,"
            f"Outline=3,"
            f"Shadow=1,"
            f"Bold=1,"
            f"Alignment=5'"
        ),
        "-c:v", "libx264", "-preset", "slow", "-crf", "18",
        "-r", "30",
        "-pix_fmt", "yuv420p", "-an",
        tmp_txt,
    ], "subtitles")

    if not subtitle_ok:
        logger.warning("Субтитры недоступны — видео без текста")
        tmp_txt = tmp_bg

    for f in [tmp_bg, srt_path]:
        if f != tmp_txt and os.path.exists(f):
            os.remove(f)

    # Шаг 3: аудио
    if music:
        ok = await run_ffmpeg([
            "ffmpeg", "-y",
            "-i", tmp_txt,
            "-i", audio_path,
            "-i", music,
            "-filter_complex",
            f"[2:a]volume=0.1,atrim=0:{duration}[bg];[1:a][bg]amix=inputs=2:duration=first[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-t", str(duration),
            "-movflags", "+faststart",
            output_path,
        ], "audio_mix")
    else:
        ok = await run_ffmpeg([
            "ffmpeg", "-y",
            "-i", tmp_txt,
            "-i", audio_path,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-t", str(duration),
            "-movflags", "+faststart",
            output_path,
        ], "audio_only")

    if os.path.exists(tmp_txt):
        os.remove(tmp_txt)

    if ok:
        size_mb = os.path.getsize(output_path) / 1024 / 1024
        logger.info(f"Видео готово: {Path(output_path).name} ({size_mb:.1f}MB, {duration:.1f}с)")

    return ok
