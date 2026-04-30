"""
telegram_sender.py — Отправка готовых видео в Telegram личку
"""
import os
from pathlib import Path
from telegram import Bot
from telegram.error import TelegramError
from loguru import logger

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_OWNER_ID  = os.getenv("TELEGRAM_OWNER_ID", "")


class TelegramSender:
    def __init__(self):
        if not TELEGRAM_BOT_TOKEN:
            logger.warning("TELEGRAM_BOT_TOKEN не задан — отправка отключена")
            self.bot = None
            return
        if not TELEGRAM_OWNER_ID:
            logger.warning("TELEGRAM_OWNER_ID не задан — отправка отключена")
            self.bot = None
            return

        self.bot = Bot(token=TELEGRAM_BOT_TOKEN)
        self.owner_id = int(TELEGRAM_OWNER_ID)
        logger.info(f"Telegram sender готов → owner_id={self.owner_id}")

    async def send_video(self, video_path: str, caption: str = "") -> bool:
        """Отправляет MP4 файл в личку владельца."""
        if not self.bot:
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
            logger.info(f"📤 Видео отправлено в Telegram: {path.name}")
            return True

        except TelegramError as e:
            logger.error(f"Ошибка отправки видео в Telegram: {e}")
            return False
