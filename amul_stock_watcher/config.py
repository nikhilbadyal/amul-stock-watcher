"""Application configuration and logging setup."""

from __future__ import annotations

import logging
import os
from typing import Dict, Optional, Union

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)


class Config:
    """Configuration values sourced from the environment."""

    TELEGRAM_BOT_TOKEN: Optional[str] = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHANNEL_ID: Optional[str] = os.getenv("TELEGRAM_CHANNEL_ID")
    PINCODE: Optional[str] = os.getenv("PINCODE", "110001")
    DEFAULT_STORE: str = os.getenv("DEFAULT_STORE", "delhi")
    REQUEST_TIMEOUT: int | float = float(os.getenv("REQUEST_TIMEOUT", "3"))
    FORCE_NOTIFY: bool = os.getenv("FORCE_NOTIFY", "False").lower() == "true"
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_DB: int = int(os.getenv("REDIS_DB", "0"))
    REDIS_PASSWORD: Optional[str] = os.getenv("REDIS_PASSWORD")
    REDIS_SSL: bool = os.getenv("REDIS_SSL", "False").lower() == "true"
    REDIS_KEY_PREFIX: str = os.getenv("REDIS_KEY_PREFIX", "amul:")
    MAX_WORKERS: int = int(os.getenv("MAX_WORKERS", "4"))


HEADERS: Dict[str, str] = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
    ),
    "Origin": "https://shop.amul.com",
    "Referer": "https://shop.amul.com/",
}
