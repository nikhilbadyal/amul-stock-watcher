"""Product availability orchestration."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from .api_client import AmulAPIClient
from .config import Config
from .models import Product
from .notifier import TelegramNotifier
from .state_manager import RedisStateManager

logger = logging.getLogger(__name__)


class ProductAvailabilityChecker:
    """Coordinate fetching, state tracking, and notifications."""

    def __init__(self) -> None:
        self.api_client = AmulAPIClient()
        self.notifier = TelegramNotifier()
        self.state_manager: Optional[RedisStateManager]
        try:
            self.state_manager = RedisStateManager()
            self.use_state_management = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis not available, falling back to basic notification: %s", exc)
            self.state_manager = None
            self.use_state_management = False

    def _extract_detailed_info(self, detailed_info: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Extract and convert detailed product information with safe defaults."""
        if not detailed_info:
            return {
                "inventory_quantity": 0,
                "weight": 0,
                "inventory_low_stock_quantity": 0,
                "total_order_count": 0,
                "compare_price": 0.0,
                "product_type": "",
                "uom": "",
            }

        # Extract numeric fields with safe conversion
        extracted: Dict[str, Any] = {
            "inventory_quantity": int(detailed_info.get("inventory_quantity", 0)),
            "weight": int(detailed_info.get("weight", 0)),
            "inventory_low_stock_quantity": int(detailed_info.get("inventory_low_stock_quantity", 0)),
            "total_order_count": int(detailed_info.get("total_order_count", 0)),
            "compare_price": float(detailed_info.get("compare_price", 0.0)),
        }

        # Extract metafields
        metafields = detailed_info.get("metafields", {})
        extracted["product_type"] = str(metafields.get("product_type", ""))
        extracted["uom"] = str(metafields.get("uom", ""))

        return extracted

    def _create_product_objects(self, raw_products: List[Dict[str, Any]], store: str) -> List[Product]:
        products: List[Product] = []
        aliases = [product.get("alias", "") for product in raw_products if product.get("alias")]
        detailed_info_map = self.api_client.get_product_details_parallel(aliases, max_workers=Config.MAX_WORKERS)

        for product in raw_products:
            alias = product.get("alias", "")
            if not alias:
                continue

            detailed_info = detailed_info_map.get(alias)
            info = self._extract_detailed_info(detailed_info)

            product_obj = Product(
                alias=alias,
                name=product.get("name", "Unknown Product"),
                available=product.get("available", 0) > 0,
                url=f"https://shop.amul.com/product/{alias}",
                store=store,
                price=float(product.get("price", 0)),
                **info,
            )
            products.append(product_obj)

        return products

    def check_availability(self) -> Tuple[List[Product], List[Product]]:
        if Config.PINCODE is None:
            raise ValueError("PINCODE must be set in the environment variables")
        store = self.api_client.get_store_from_pincode(Config.PINCODE) if Config.PINCODE else Config.DEFAULT_STORE
        self.api_client.set_store_preferences(store)
        raw_products = self.api_client.get_products()
        if not raw_products:
            raise ValueError("No products found in the API response")
        logger.info("Retrieved %s products from API for store: %s", len(raw_products), store)
        products = self._create_product_objects(raw_products, store)
        available = [p for p in products if p.available]
        unavailable = [p for p in products if not p.available]
        return available, unavailable

    def _handle_notifications(
        self,
        all_products: List[Product],
        available_products: List[Product],
        should_force_notify: bool,
        dry_run: bool,
    ) -> None:
        if should_force_notify:
            logger.info("Force notify enabled. Sending status for all %s products", len(all_products))
            self.notifier.send_notification(all_products, force=True, log_to_console=dry_run)
            return

        if self.use_state_management and self.state_manager:
            newly_available = self.state_manager.get_newly_available_products(all_products)
            if newly_available:
                logger.info("Found %s newly available products", len(newly_available))
                self.notifier.send_notification(newly_available, log_to_console=dry_run)
            else:
                logger.info("No newly available products to notify about")
            return

        if available_products:
            logger.info(
                "Redis not available - sending basic notification for %s available products",
                len(available_products),
            )
            self.notifier.send_notification(available_products, log_to_console=dry_run)
        else:
            logger.info("No available products to notify about")

    def run(self, force_notify: Optional[bool] = None, dry_run: bool = False) -> None:
        available_products, unavailable_products = self.check_availability()
        all_products = available_products + unavailable_products
        should_force_notify = force_notify if force_notify is not None else Config.FORCE_NOTIFY
        self._handle_notifications(all_products, available_products, should_force_notify, dry_run)
        logger.info(
            "Current status - Available: %s, Unavailable: %s",
            len(available_products),
            len(unavailable_products),
        )
        for product in unavailable_products:
            logger.debug("Product unavailable: %s", product.name)
