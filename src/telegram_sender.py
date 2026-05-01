"""
telegram_sender.py — Отправка видео в личку + команды управления + статистика
Команды: /stats, /pause, /resume
"""
import asyncio
import os
import glob
from datetime import datetime
from pathlib import Path
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import TelegramError
from loguru import logger

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_OWNER_ID  = os.getenv("TELEGRAM_OWNER_ID", "")
OUTPUT_DIR         = os.getenv("OUTPUT_DIR", "/app/output")
AUDIO_DIR          = "/app/audio"
# Хранить аудио не дольше N часов
AUDIO_MAX_AGE_HOURS = int(os.getenv("AUDIO_MAX_AGE_HOURS", "24"))


class TelegramSender:
    def __init__(self):
        self.bot       = None
        self.owner_id  = None
        self.paused    = False
        self._app      = None

        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_OWNER_ID:
            logger.warning("TELEGRAM_BOT_TOKEN или TELEGRAM_OWNER_ID не задан — отправка отключена")
            return

        self.bot      = Bot(token=TELEGRAM_BOT_TOKEN)
        self.owner_id = int(TELEGRAM_OWNER_ID)
        logger.info(f"Telegram sender готов → owner_id={self.owner_id}")

    # ── Отправка видео ────────────────────────────────────────

    async def send_video(self, video_path: str, caption: str = "") -> bool:
        if not self.bot or self.paused:
            if self.paused:
                logger.info("Отправка на паузе — видео сохранено локально")
            return False

        path = Path(video_path)
        if not path.exists():
            logger.error(f"Видео не найдено: {video_path}")
            return False

        try:
            with open(video_path, "rb") as f:
                await self.bot.send_document(
                    chat_id=self.owner_id,
                    document=f,
                    filename=path.name,
                    caption=caption[:1024] if caption else f"🎬 {path.name}",
                )
            logger.info(f"📤 Видео отправлено: {path.name}")
            return True
        except TelegramError as e:
            logger.error(f"Ошибка отправки: {e}")
            return False

    # ── Статистика ────────────────────────────────────────────

    def _build_stats(self) -> str:
        videos   = list(Path(OUTPUT_DIR).glob("*.mp4")) if Path(OUTPUT_DIR).exists() else []
        today    = datetime.utcnow().date()
        today_vids = [v for v in videos if datetime.utcfromtimestamp(v.stat().st_mtime).date() == today]
        total_mb   = sum(v.stat().st_size for v in videos) / 1024 / 1024
        audio_files = list(Path(AUDIO_DIR).glob("*.mp3")) if Path(AUDIO_DIR).exists() else []

        return (
            f"📊 *Статистика Reels Bot*\n\n"
            f"🎬 Видео сегодня: *{len(today_vids)}*\n"
            f"🎬 Видео всего: *{len(videos)}*\n"
            f"💾 Занято места: *{total_mb:.1f} MB*\n"
            f"🔊 Аудио файлов: *{len(audio_files)}*\n"
            f"⏸ Пауза: *{'да' if self.paused else 'нет'}*\n"
            f"🕐 Время UTC: *{datetime.utcnow().strftime('%H:%M:%S')}*"
        )

    async def send_daily_stats(self):
        """Отправляет ежедневную статистику."""
        if not self.bot:
            return
        try:
            await self.bot.send_message(
                chat_id=self.owner_id,
                text=self._build_stats(),
                parse_mode="Markdown",
            )
            logger.info("Статистика отправлена")
        except TelegramError as e:
            logger.error(f"Ошибка отправки статистики: {e}")

    # ── Автоочистка аудио ─────────────────────────────────────

    def cleanup_audio(self):
        """Удаляет аудиофайлы старше AUDIO_MAX_AGE_HOURS часов."""
        audio_dir = Path(AUDIO_DIR)
        if not audio_dir.exists():
            return
        now     = datetime.utcnow().timestamp()
        max_age = AUDIO_MAX_AGE_HOURS * 3600
        deleted = 0
        for f in audio_dir.glob("*.mp3"):
            if now - f.stat().st_mtime > max_age:
                f.unlink()
                deleted += 1
        if deleted:
            logger.info(f"Автоочистка: удалено {deleted} аудиофайлов")

    # ── Команды бота ─────────────────────────────────────────

    def _is_owner(self, update: Update) -> bool:
        return str(update.effective_user.id) == str(self.owner_id)

    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_owner(update):
            return
        await update.message.reply_text(
            "👋 Reels Bot активен!\n\n"
            "Команды:\n"
            "/stats — статистика\n"
            "/pause — пауза отправки\n"
            "/resume — возобновить"
        )

    async def cmd_stats(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_owner(update):
            return
        await update.message.reply_text(self._build_stats(), parse_mode="Markdown")

    async def cmd_pause(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_owner(update):
            return
        self.paused = True
        await update.message.reply_text("⏸ Отправка видео приостановлена. /resume чтобы возобновить.")
        logger.info("Отправка поставлена на паузу")

    async def cmd_resume(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_owner(update):
            return
        self.paused = False
        await update.message.reply_text("▶️ Отправка видео возобновлена!")
        logger.info("Отправка возобновлена")

    async def start_polling(self):
        """Запускает polling для команд в фоне."""
        if not self.bot:
            return
        try:
            self._app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
            self._app.add_handler(CommandHandler("start",  self.cmd_start))
            self._app.add_handler(CommandHandler("stats",  self.cmd_stats))
            self._app.add_handler(CommandHandler("pause",  self.cmd_pause))
            self._app.add_handler(CommandHandler("resume", self.cmd_resume))
            await self._app.initialize()
            await self._app.start()
            await self._app.updater.start_polling(drop_pending_updates=True)
            logger.info("Telegram команды активны: /stats /pause /resume")
        except Exception as e:
            logger.error(f"Ошибка запуска polling: {e}")

    async def stop_polling(self):
        if self._app:
            try:
                await self._app.updater.stop()
                await self._app.stop()
                await self._app.shutdown()
            except Exception:
                pass
