"""Redis-backed state tracking for product availability."""

from __future__ import annotations

import logging
from typing import List, Set

import redis

from .config import Config
from .models import Product

logger = logging.getLogger(__name__)


class RedisStateManager:
    """Manage cached product availability state in Redis."""

    def __init__(self) -> None:
        try:
            self.redis_client = redis.Redis(
                host=Config.REDIS_HOST,
                port=Config.REDIS_PORT,
                db=Config.REDIS_DB,
                password=Config.REDIS_PASSWORD,
                decode_responses=True,
                ssl=Config.REDIS_SSL,
                socket_connect_timeout=3,
                socket_timeout=3,
            )
            self.redis_client.ping()
            logger.info("Connected to Redis successfully")
        except Exception as exc:  # noqa: BLE001 - Keep broad except but log.
            logger.error("Failed to connect to Redis: %s", exc)
            raise

    def get_previous_state(self, store: str) -> Set[str]:
        key = f"{Config.REDIS_KEY_PREFIX}{store}:available"
        try:
            aliases = self.redis_client.smembers(key)
            return set(aliases) if aliases else set()
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to get previous state from Redis: %s", exc)
            return set()

    def update_state(self, store: str, available_aliases: Set[str]) -> bool:
        key = f"{Config.REDIS_KEY_PREFIX}{store}:available"
        try:
            self.redis_client.delete(key)
            if available_aliases:
                self.redis_client.sadd(key, *available_aliases)
            self.redis_client.expire(key, 7 * 24 * 60 * 60)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to update state in Redis: %s", exc)
            return False

    def get_newly_available_products(self, current_products: List[Product]) -> List[Product]:
        if not current_products:
            return []
        store = current_products[0].store
        current_available = {p.alias for p in current_products if p.available}
        previous_available = self.get_previous_state(store)
        newly_available_aliases = current_available - previous_available
        self.update_state(store, current_available)
        newly_available_products = [
            p for p in current_products if p.available and p.alias in newly_available_aliases
        ]
        logger.info(
            "Previous available: %s, Current available: %s, Newly available: %s",
            len(previous_available),
            len(current_available),
            len(newly_available_products),
        )
        return newly_available_products
