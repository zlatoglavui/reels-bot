"""
video/composer.py — Сборка финального видео через FFmpeg
Формат: 1080x1920 (9:16) с прогресс-баром и фоновой музыкой
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
    return (text
            .replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace(":", "\\:")
            .replace(",", "\\,")
            .replace("[", "\\[")
            .replace("]", "\\]")
            .replace("%", "\\%"))


def build_subtitle_filter(phrases: list[str], duration: float, font: str) -> str:
    if not phrases:
        return "null"
    time_per = duration / len(phrases)
    filters = []
    for i, phrase in enumerate(phrases):
        start = i * time_per
        end   = start + time_per
        safe  = escape_ffmpeg(phrase)
        filters.append(
            f"drawtext=fontfile='{font}':text='{safe}'"
            f":fontsize=72:fontcolor=white"
            f":shadowcolor=black@0.8:shadowx=3:shadowy=3"
            f":x=(w-text_w)/2:y=(h-text_h)/2+150"
            f":enable='between(t,{start:.2f},{end:.2f})'"
        )
    return ",".join(filters)


def build_progress_bar(duration: float) -> str:
    bar_h = 8
    bar_y = HEIGHT - 40
    return (
        f"drawbox=x=0:y={bar_y}:w={WIDTH}:h={bar_h}"
        f":color=white@0.3:t=fill,"
        f"drawbox=x=0:y={bar_y}"
        f":w='min({WIDTH}\\,{WIDTH}*t/{duration:.2f})'"
        f":h={bar_h}:color=white@0.9:t=fill"
    )


def get_music_file() -> str | None:
    music_dir = Path(MUSIC_DIR)
    if not music_dir.exists():
        return None
    tracks = list(music_dir.glob("*.mp3")) + list(music_dir.glob("*.m4a"))
    return str(random.choice(tracks)) if tracks else None


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
                        content = await r.read()
                        path.write_bytes(content)
                        logger.info(f"Музыка скачана: {name}")
        except Exception as e:
            logger.warning(f"Не удалось скачать музыку {name}: {e}")


async def run_ffmpeg(cmd: list[str]) -> bool:
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
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c=0x0a0a2e:size={WIDTH}x{HEIGHT}:rate=30:duration={duration}",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-t", str(duration), output_path
    ]
    return await run_ffmpeg(cmd)


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

    overlay   = f"drawbox=x=0:y=0:w={WIDTH}:h={HEIGHT}:color=black@0.5:t=fill"
    hook_filt = (
        f"drawtext=fontfile='{font}':text='{hook}'"
        f":fontsize=52:fontcolor=yellow"
        f":shadowcolor=black@0.9:shadowx=2:shadowy=2"
        f":x=(w-text_w)/2:y=160"
        f":enable='between(t,0,{duration:.2f})'"
    )
    watermark = (
        f"drawtext=fontfile='{font}':text='@propustilnews'"
        f":fontsize=34:fontcolor=white@0.5"
        f":x=(w-text_w)/2:y={HEIGHT - 80}"
    )

    full_vf = f"{overlay},{hook_filt},{sub_filt},{prog_bar},{watermark}"

    # Готовим фон — перекодируем в совместимый формат
    tmp_bg = output_path.replace(".mp4", "_bg.mp4")
    if background_path and os.path.exists(background_path):
        transcode_ok = await run_ffmpeg([
            "ffmpeg", "-y",
            "-stream_loop", "-1",
            "-i", background_path,
            "-vf", f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT}",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-an",
            "-t", str(duration + 2),
            tmp_bg,
        ])
        if transcode_ok:
            bg_input  = ["-i", tmp_bg]
            bg_filter = full_vf
        else:
            logger.warning("Перекодирование фона не удалось — используем градиент")
            await create_gradient_background(duration, tmp_bg)
            bg_input  = ["-i", tmp_bg]
            bg_filter = full_vf
    else:
        await create_gradient_background(duration, tmp_bg)
        bg_input  = ["-i", tmp_bg]
        bg_filter = full_vf

    # Аудио: голос + музыка (если есть)
    if music:
        audio_inputs = ["-i", audio_path, "-i", music]
        audio_filter = (
            f"[1:a]volume=0.12,atrim=0:{duration}[bg];"
            f"[0:a][bg]amix=inputs=2:duration=first[aout]"
        )
        audio_map   = ["-map", "0:v", "-map", "[aout]"]
        audio_extra = ["-filter_complex", audio_filter] + audio_map
    else:
        audio_inputs = ["-i", audio_path]
        audio_extra  = ["-map", "0:v", "-map", "1:a"]

    cmd = (
        ["ffmpeg", "-y"]
        + bg_input
        + audio_inputs
        + ["-vf", bg_filter]
        + audio_extra
        + [
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-t", str(duration), "-shortest",
            "-movflags", "+faststart",
            output_path,
        ]
    )

    success = await run_ffmpeg(cmd)

    if os.path.exists(tmp_bg):
        os.remove(tmp_bg)

    if success:
        size_mb = os.path.getsize(output_path) / 1024 / 1024
        logger.info(f"Видео готово: {Path(output_path).name} ({size_mb:.1f}MB, {duration:.1f}с)")

    return success
