"""
video/composer.py — Сборка видео через FFmpeg (максимально совместимая версия)
"""
import asyncio
import os
import random
from pathlib import Path
from loguru import logger

WIDTH  = 1080
HEIGHT = 1920
FONT   = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_FALLBACK = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/app/output")
MUSIC_DIR  = "/app/music"


def get_font() -> str:
    for f in [FONT, FONT_FALLBACK]:
        if os.path.exists(f):
            return f
    return "DejaVuSans-Bold"


def split_into_phrases(text: str, words_per_phrase: int = 4) -> list[str]:
    words = text.split()
    phrases = []
    for i in range(0, len(words), words_per_phrase):
        phrases.append(" ".join(words[i:i + words_per_phrase]))
    return phrases


def escape_ffmpeg(text: str) -> str:
    text = text.replace("\\", "\\\\")
    text = text.replace("'",  "\\'")
    text = text.replace(":",  "\\:")
    text = text.replace(",",  "\\,")
    text = text.replace("[",  "\\[")
    text = text.replace("]",  "\\]")
    text = text.replace("%",  "\\%")
    for ch in "!?;@#$^&*()":
        text = text.replace(ch, "")
    return text.strip()


def build_subtitle_filter(phrases: list[str], duration: float, font: str) -> str:
    if not phrases:
        return ""
    time_per = duration / len(phrases)
    filters = []
    for i, phrase in enumerate(phrases):
        start = i * time_per
        end   = start + time_per
        safe  = escape_ffmpeg(phrase)
        if not safe:
            continue
        filters.append(
            f"drawtext=fontfile='{font}':text='{safe}'"
            f":fontsize=68:fontcolor=white"
            f":shadowcolor=black@0.8:shadowx=3:shadowy=3"
            f":x=(w-text_w)/2:y=(h-text_h)/2+150"
            f":enable='between(t,{start:.2f},{end:.2f})'"
        )
    return ",".join(filters)


def build_progress_bar(duration: float) -> str:
    bar_y = HEIGHT - 40
    return (
        f"drawbox=x=0:y={bar_y}:w={WIDTH}:h=8:color=white@0.3:t=fill,"
        f"drawbox=x=0:y={bar_y}"
        f":w='min({WIDTH}\\,{WIDTH}*t/{duration:.2f})'"
        f":h=8:color=white@0.9:t=fill"
    )


def get_music_file() -> str | None:
    music_dir = Path(MUSIC_DIR)
    if not music_dir.exists():
        return None
    tracks = list(music_dir.glob("*.mp3")) + list(music_dir.glob("*.m4a"))
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


async def run_ffmpeg(cmd: list[str]) -> bool:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.error(f"FFmpeg ошибка: {stderr.decode()[-400:]}")
        return False
    return True


async def make_background(duration: float, output_path: str) -> bool:
    return await run_ffmpeg([
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c=0x0d0d1a:size={WIDTH}x{HEIGHT}:rate=25",
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-pix_fmt", "yuv420p",
        output_path,
    ])


async def compose_video(
    background_path: str | None,
    audio_path: str,
    script: dict,
    output_path: str,
    duration: float,
) -> bool:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    font     = get_font()
    phrases  = split_into_phrases(script.get("full_text", ""), words_per_phrase=4)
    sub_filt = build_subtitle_filter(phrases, duration, font)
    prog_bar = build_progress_bar(duration)
    hook     = escape_ffmpeg(script.get("hook", ""))
    music    = get_music_file()

    overlay = f"drawbox=x=0:y=0:w={WIDTH}:h={HEIGHT}:color=black@0.45:t=fill"
    parts   = [overlay]

    if hook:
        parts.append(
            f"drawtext=fontfile='{font}':text='{hook}'"
            f":fontsize=50:fontcolor=yellow"
            f":shadowcolor=black@0.9:shadowx=2:shadowy=2"
            f":x=(w-text_w)/2:y=160"
        )

    if sub_filt:
        parts.append(sub_filt)

    parts.append(prog_bar)
    parts.append(
        f"drawtext=fontfile='{font}':text='propustilnews'"
        f":fontsize=32:fontcolor=white@0.5"
        f":x=(w-text_w)/2:y={HEIGHT - 80}"
    )

    vf = ",".join(parts)

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
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-pix_fmt", "yuv420p", "-an",
            tmp_bg,
        ])

    if not bg_ok:
        logger.info("Градиентный фон")
        bg_ok = await make_background(duration, tmp_bg)

    if not bg_ok:
        logger.error("Не удалось создать фон")
        return False

    # Шаг 2: текст поверх фона
    tmp_txt = output_path.replace(".mp4", "_txt.mp4")
    ok = await run_ffmpeg([
        "ffmpeg", "-y",
        "-i", tmp_bg,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-an",
        tmp_txt,
    ])

    if os.path.exists(tmp_bg):
        os.remove(tmp_bg)

    if not ok:
        return False

    # Шаг 3: добавляем аудио
    if music:
        ok = await run_ffmpeg([
            "ffmpeg", "-y",
            "-i", tmp_txt,
            "-i", audio_path,
            "-i", music,
            "-filter_complex",
            f"[2:a]volume=0.1,atrim=0:{duration}[bg];[1:a][bg]amix=inputs=2:duration=first[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
            "-t", str(duration), "-movflags", "+faststart",
            output_path,
        ])
    else:
        ok = await run_ffmpeg([
            "ffmpeg", "-y",
            "-i", tmp_txt,
            "-i", audio_path,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
            "-t", str(duration), "-movflags", "+faststart",
            output_path,
        ])

    if os.path.exists(tmp_txt):
        os.remove(tmp_txt)

    if ok:
        size_mb = os.path.getsize(output_path) / 1024 / 1024
        logger.info(f"Видео готово: {Path(output_path).name} ({size_mb:.1f}MB, {duration:.1f}с)")

    return ok"""
video/composer.py — Сборка видео через FFmpeg (максимально совместимая версия)
"""
import asyncio
import os
import random
from pathlib import Path
from loguru import logger

WIDTH  = 1080
HEIGHT = 1920
FONT   = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_FALLBACK = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/app/output")
MUSIC_DIR  = "/app/music"


def get_font() -> str:
    for f in [FONT, FONT_FALLBACK]:
        if os.path.exists(f):
            return f
    return "DejaVuSans-Bold"


def split_into_phrases(text: str, words_per_phrase: int = 4) -> list[str]:
    words = text.split()
    phrases = []
    for i in range(0, len(words), words_per_phrase):
        phrases.append(" ".join(words[i:i + words_per_phrase]))
    return phrases


def escape_ffmpeg(text: str) -> str:
    text = text.replace("\\", "\\\\")
    text = text.replace("'",  "\\'")
    text = text.replace(":",  "\\:")
    text = text.replace(",",  "\\,")
    text = text.replace("[",  "\\[")
    text = text.replace("]",  "\\]")
    text = text.replace("%",  "\\%")
    for ch in "!?;@#$^&*()":
        text = text.replace(ch, "")
    return text.strip()


def build_subtitle_filter(phrases: list[str], duration: float, font: str) -> str:
    if not phrases:
        return ""
    time_per = duration / len(phrases)
    filters = []
    for i, phrase in enumerate(phrases):
        start = i * time_per
        end   = start + time_per
        safe  = escape_ffmpeg(phrase)
        if not safe:
            continue
        filters.append(
            f"drawtext=fontfile='{font}':text='{safe}'"
            f":fontsize=68:fontcolor=white"
            f":shadowcolor=black@0.8:shadowx=3:shadowy=3"
            f":x=(w-text_w)/2:y=(h-text_h)/2+150"
            f":enable='between(t,{start:.2f},{end:.2f})'"
        )
    return ",".join(filters)


def build_progress_bar(duration: float) -> str:
    bar_y = HEIGHT - 40
    return (
        f"drawbox=x=0:y={bar_y}:w={WIDTH}:h=8:color=white@0.3:t=fill,"
        f"drawbox=x=0:y={bar_y}"
        f":w='min({WIDTH}\\,{WIDTH}*t/{duration:.2f})'"
        f":h=8:color=white@0.9:t=fill"
    )


def get_music_file() -> str | None:
    music_dir = Path(MUSIC_DIR)
    if not music_dir.exists():
        return None
    tracks = list(music_dir.glob("*.mp3")) + list(music_dir.glob("*.m4a"))
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


async def run_ffmpeg(cmd: list[str]) -> bool:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.error(f"FFmpeg ошибка: {stderr.decode()[-400:]}")
        return False
    return True


async def make_background(duration: float, output_path: str) -> bool:
    return await run_ffmpeg([
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c=0x0d0d1a:size={WIDTH}x{HEIGHT}:rate=25",
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-pix_fmt", "yuv420p",
        output_path,
    ])


async def compose_video(
    background_path: str | None,
    audio_path: str,
    script: dict,
    output_path: str,
    duration: float,
) -> bool:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    font     = get_font()
    phrases  = split_into_phrases(script.get("full_text", ""), words_per_phrase=4)
    sub_filt = build_subtitle_filter(phrases, duration, font)
    prog_bar = build_progress_bar(duration)
    hook     = escape_ffmpeg(script.get("hook", ""))
    music    = get_music_file()

    overlay = f"drawbox=x=0:y=0:w={WIDTH}:h={HEIGHT}:color=black@0.45:t=fill"
    parts   = [overlay]

    if hook:
        parts.append(
            f"drawtext=fontfile='{font}':text='{hook}'"
            f":fontsize=50:fontcolor=yellow"
            f":shadowcolor=black@0.9:shadowx=2:shadowy=2"
            f":x=(w-text_w)/2:y=160"
        )

    if sub_filt:
        parts.append(sub_filt)

    parts.append(prog_bar)
    parts.append(
        f"drawtext=fontfile='{font}':text='propustilnews'"
        f":fontsize=32:fontcolor=white@0.5"
        f":x=(w-text_w)/2:y={HEIGHT - 80}"
    )

    vf = ",".join(parts)

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
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-pix_fmt", "yuv420p", "-an",
            tmp_bg,
        ])

    if not bg_ok:
        logger.info("Градиентный фон")
        bg_ok = await make_background(duration, tmp_bg)

    if not bg_ok:
        logger.error("Не удалось создать фон")
        return False

    # Шаг 2: текст поверх фона
    tmp_txt = output_path.replace(".mp4", "_txt.mp4")
    ok = await run_ffmpeg([
        "ffmpeg", "-y",
        "-i", tmp_bg,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-an",
        tmp_txt,
    ])

    if os.path.exists(tmp_bg):
        os.remove(tmp_bg)

    if not ok:
        return False

    # Шаг 3: добавляем аудио
    if music:
        ok = await run_ffmpeg([
            "ffmpeg", "-y",
            "-i", tmp_txt,
            "-i", audio_path,
            "-i", music,
            "-filter_complex",
            f"[2:a]volume=0.1,atrim=0:{duration}[bg];[1:a][bg]amix=inputs=2:duration=first[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
            "-t", str(duration), "-movflags", "+faststart",
            output_path,
        ])
    else:
        ok = await run_ffmpeg([
            "ffmpeg", "-y",
            "-i", tmp_txt,
            "-i", audio_path,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
            "-t", str(duration), "-movflags", "+faststart",
            output_path,
        ])

    if os.path.exists(tmp_txt):
        os.remove(tmp_txt)

    if ok:
        size_mb = os.path.getsize(output_path) / 1024 / 1024
        logger.info(f"Видео готово: {Path(output_path).name} ({size_mb:.1f}MB, {duration:.1f}с)")

    return ok"""
video/composer.py — Сборка видео через FFmpeg (максимально совместимая версия)
"""
import asyncio
import os
import random
from pathlib import Path
from loguru import logger

WIDTH  = 1080
HEIGHT = 1920
FONT   = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_FALLBACK = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/app/output")
MUSIC_DIR  = "/app/music"


def get_font() -> str:
    for f in [FONT, FONT_FALLBACK]:
        if os.path.exists(f):
            return f
    return "DejaVuSans-Bold"


def split_into_phrases(text: str, words_per_phrase: int = 4) -> list[str]:
    words = text.split()
    phrases = []
    for i in range(0, len(words), words_per_phrase):
        phrases.append(" ".join(words[i:i + words_per_phrase]))
    return phrases


def escape_ffmpeg(text: str) -> str:
    text = text.replace("\\", "\\\\")
    text = text.replace("'",  "\\'")
    text = text.replace(":",  "\\:")
    text = text.replace(",",  "\\,")
    text = text.replace("[",  "\\[")
    text = text.replace("]",  "\\]")
    text = text.replace("%",  "\\%")
    for ch in "!?;@#$^&*()":
        text = text.replace(ch, "")
    return text.strip()


def build_subtitle_filter(phrases: list[str], duration: float, font: str) -> str:
    if not phrases:
        return ""
    time_per = duration / len(phrases)
    filters = []
    for i, phrase in enumerate(phrases):
        start = i * time_per
        end   = start + time_per
        safe  = escape_ffmpeg(phrase)
        if not safe:
            continue
        filters.append(
            f"drawtext=fontfile='{font}':text='{safe}'"
            f":fontsize=68:fontcolor=white"
            f":shadowcolor=black@0.8:shadowx=3:shadowy=3"
            f":x=(w-text_w)/2:y=(h-text_h)/2+150"
            f":enable='between(t,{start:.2f},{end:.2f})'"
        )
    return ",".join(filters)


def build_progress_bar(duration: float) -> str:
    bar_y = HEIGHT - 40
    return (
        f"drawbox=x=0:y={bar_y}:w={WIDTH}:h=8:color=white@0.3:t=fill,"
        f"drawbox=x=0:y={bar_y}"
        f":w='min({WIDTH}\\,{WIDTH}*t/{duration:.2f})'"
        f":h=8:color=white@0.9:t=fill"
    )


def get_music_file() -> str | None:
    music_dir = Path(MUSIC_DIR)
    if not music_dir.exists():
        return None
    tracks = list(music_dir.glob("*.mp3")) + list(music_dir.glob("*.m4a"))
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


async def run_ffmpeg(cmd: list[str]) -> bool:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.error(f"FFmpeg ошибка: {stderr.decode()[-400:]}")
        return False
    return True


async def make_background(duration: float, output_path: str) -> bool:
    return await run_ffmpeg([
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c=0x0d0d1a:size={WIDTH}x{HEIGHT}:rate=25",
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-pix_fmt", "yuv420p",
        output_path,
    ])


async def compose_video(
    background_path: str | None,
    audio_path: str,
    script: dict,
    output_path: str,
    duration: float,
) -> bool:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    font     = get_font()
    phrases  = split_into_phrases(script.get("full_text", ""), words_per_phrase=4)
    sub_filt = build_subtitle_filter(phrases, duration, font)
    prog_bar = build_progress_bar(duration)
    hook     = escape_ffmpeg(script.get("hook", ""))
    music    = get_music_file()

    overlay = f"drawbox=x=0:y=0:w={WIDTH}:h={HEIGHT}:color=black@0.45:t=fill"
    parts   = [overlay]

    if hook:
        parts.append(
            f"drawtext=fontfile='{font}':text='{hook}'"
            f":fontsize=50:fontcolor=yellow"
            f":shadowcolor=black@0.9:shadowx=2:shadowy=2"
            f":x=(w-text_w)/2:y=160"
        )

    if sub_filt:
        parts.append(sub_filt)

    parts.append(prog_bar)
    parts.append(
        f"drawtext=fontfile='{font}':text='propustilnews'"
        f":fontsize=32:fontcolor=white@0.5"
        f":x=(w-text_w)/2:y={HEIGHT - 80}"
    )

    vf = ",".join(parts)

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
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-pix_fmt", "yuv420p", "-an",
            tmp_bg,
        ])

    if not bg_ok:
        logger.info("Градиентный фон")
        bg_ok = await make_background(duration, tmp_bg)

    if not bg_ok:
        logger.error("Не удалось создать фон")
        return False

    # Шаг 2: текст поверх фона
    tmp_txt = output_path.replace(".mp4", "_txt.mp4")
    ok = await run_ffmpeg([
        "ffmpeg", "-y",
        "-i", tmp_bg,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-an",
        tmp_txt,
    ])

    if os.path.exists(tmp_bg):
        os.remove(tmp_bg)

    if not ok:
        return False

    # Шаг 3: добавляем аудио
    if music:
        ok = await run_ffmpeg([
            "ffmpeg", "-y",
            "-i", tmp_txt,
            "-i", audio_path,
            "-i", music,
            "-filter_complex",
            f"[2:a]volume=0.1,atrim=0:{duration}[bg];[1:a][bg]amix=inputs=2:duration=first[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
            "-t", str(duration), "-movflags", "+faststart",
            output_path,
        ])
    else:
        ok = await run_ffmpeg([
            "ffmpeg", "-y",
            "-i", tmp_txt,
            "-i", audio_path,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
            "-t", str(duration), "-movflags", "+faststart",
            output_path,
        ])

    if os.path.exists(tmp_txt):
        os.remove(tmp_txt)

    if ok:
        size_mb = os.path.getsize(output_path) / 1024 / 1024
        logger.info(f"Видео готово: {Path(output_path).name} ({size_mb:.1f}MB, {duration:.1f}с)")

    return ok
