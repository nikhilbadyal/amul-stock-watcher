"""Telegram notification helper."""

from __future__ import annotations

import logging
from typing import List

import requests

from .config import Config
from .models import Product

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Send product availability updates to Telegram."""

    @staticmethod
    def send_notification(
        products: List[Product], force: bool = False, log_to_console: bool = False
    ) -> bool:
        if not all([Config.TELEGRAM_BOT_TOKEN, Config.TELEGRAM_CHANNEL_ID]):
            log_to_console = True

        if not products:
            return True

        products_to_notify = products if force else [p for p in products if p.available]
        if not products_to_notify:
            return True

        message = "📊 Product Status Report\n\n" if force else "🎉 New Products Available!\n\n"
        for product in products_to_notify:
            message += product.to_telegram_string() + "\n"
        message += (
            "─" * 25
            + "\n"
            + "🚀 Find more cool projects at:\n"
            + "👨‍💻 @nikhilbadyal_projects"
        )

        if log_to_console:
            print("\n" + "=" * 50)
            print("DRY RUN - Telegram Notification Preview:")
            print("=" * 50)
            print(message)
            print("=" * 50)
            logger.info("DRY RUN: Would notify about %s products", len(products_to_notify))
            return True

        if not all([Config.TELEGRAM_BOT_TOKEN, Config.TELEGRAM_CHANNEL_ID]):
            logger.error("Telegram credentials are not set.")
            return False

        url = f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": Config.TELEGRAM_CHANNEL_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }

        try:
            response = requests.post(url, json=payload, timeout=float(Config.REQUEST_TIMEOUT))
            if response.ok:
                logger.info("Notification sent for %s products", len(products_to_notify))
                return True
            logger.error("Telegram API error: %s", response.status_code)
            return False
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to send Telegram notification: %s", exc)
            return False
