import os
import json
import requests
from typing import List, Dict, Optional, Tuple, Any, Union
from dataclasses import dataclass
import logging
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


# === Configuration and Constants ===
class Config:
    TELEGRAM_BOT_TOKEN: Optional[str] = os.getenv('TELEGRAM_BOT_TOKEN')
    TELEGRAM_CHANNEL_ID: Optional[str] = os.getenv('TELEGRAM_CHANNEL_ID')
    PINCODE: Optional[str] = os.getenv('PINCODE')
    DEFAULT_STORE: str = os.getenv('DEFAULT_STORE','jandk')
    REQUEST_TIMEOUT: Union[int, float] = float(os.getenv('REQUEST_TIMEOUT', '3'))
    FORCE_NOTIFY: bool = os.getenv('FORCE_NOTIFY', 'False').lower() == 'true'


HEADERS: Dict[str, str] = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Origin": "https://shop.amul.com",
    "Referer": "https://shop.amul.com/",
}


# === Data Models ===
@dataclass
class Product:
    alias: str
    name: str
    available: bool
    url: str
    store: str


# === Logging Setup ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# === API Client ===
class AmulAPIClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def _make_request(self, method: str, url: str, **kwargs: Any) -> Optional[Dict[str, Any]]:
        """Generic request handler with error handling.

        Handles:
        - JSON responses (returns parsed dict)
        - Plain text success responses (returns {"status": "success"})
        - All other cases (returns None)
        """
        try:
            response = self.session.request(
                method,
                url,
                timeout=float(Config.REQUEST_TIMEOUT),
                **kwargs
            )
            response.raise_for_status()

            # First try to parse as JSON
            try:
                return response.json() # type:ignore[no-any-return]
            except ValueError:
                # If not JSON, check for plain text success message
                if response.text.strip().lower() in ("updated successfully", "ok", "success"):
                    return {"status": "success"}

                # For other plain text responses, return the text in a structured way
                return {"text_response": response.text.strip()}

        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {e}")
            return None

    def get_products(self) -> List[Dict[str, Any]]:
        """Fetch protein products from Amul API."""
        url = "https://shop.amul.com/api/1/entity/ms.products"
        params = {
            "fields[name]": 1,
            "fields[brand]": 1,
            "fields[categories]": 1,
            "fields[collections]": 1,
            "fields[alias]": 1,
            "fields[sku]": 1,
            "fields[price]": 1,
            "fields[compare_price]": 1,
            "fields[original_price]": 1,
            "fields[images]": 1,
            "fields[metafields]": 1,
            "fields[discounts]": 1,
            "fields[catalog_only]": 1,
            "fields[is_catalog]": 1,
            "fields[seller]": 1,
            "fields[available]": 1,
            "fields[inventory_quantity]": 1,
            "fields[net_quantity]": 1,
            "fields[num_reviews]": 1,
            "fields[avg_rating]": 1,
            "fields[inventory_low_stock_quantity]": 1,
            "fields[inventory_allow_out_of_stock]": 1,
            "filters[0][field]": "categories",
            "filters[0][value][0]": "protein",
            "filters[0][operator]": "in",
            "facets": "true",
            "facetgroup": "default_category_facet",
            "limit": 100,
            "total": 1,
            "start": 0
        }

        data = self._make_request("GET", url, params=params)
        return data.get('data', []) if data else []

    def get_store_from_pincode(self, pincode: str) -> str:
        """Get store name from pincode API."""
        url = "https://shop.amul.com/entity/pincode"
        params = {
            "limit": 50,
            "filters[0][field]": "pincode",
            "filters[0][value]": pincode,
            "filters[0][operator]": "regex",
            "cf_cache": "1h"
        }
        logger.debug(f"Getting store from pincode: {pincode}")

        data = self._make_request("GET", url, params=params)
        if data and data.get('records'):
            store = data['records'][0].get('substore', Config.DEFAULT_STORE)
            if store is None:
                return Config.DEFAULT_STORE
            logger.info(f"Store found for pincode {pincode}: {store}")
            return str(store)
        return Config.DEFAULT_STORE or ""

    def set_store_preferences(self, store: str) -> bool:
        """Set store preferences on the website."""
        url = "https://shop.amul.com/entity/ms.settings/_/setPreferences"
        logger.debug(f"Setting store preferences to {store}")
        payload = {"data": {"store": store}}
        response = self._make_request("PUT", url, data=json.dumps(payload))
        return response is not None


# === Notification Service ===
class TelegramNotifier:
    @staticmethod
    def send_notification(products: List[Product], force: bool = False) -> bool:
        """Send consolidated product availability notification via Telegram.

        Args:
            products: List of products to notify about
            force: If True, send notification regardless of availability status
        """
        if not all([Config.TELEGRAM_BOT_TOKEN, Config.TELEGRAM_CHANNEL_ID]):
            logger.error("Telegram credentials are not set.")
            return False

        if not products:
            return True

        # Filter products based on availability unless force is True
        products_to_notify = products if force else [p for p in products if p.available]

        if not products_to_notify:
            return True

        message = "🎉 Products Available!\n\n" if not force else "📊 Product Status Report\n\n"
        for product in products_to_notify:
            status = "✅ Available" if product.available else "❌ Unavailable"
            message += (
                f"• {product.name}\n"
                f"  Status: {status}\n"
                f"  Store: {product.store}\n"
                f"  Link: {product.url}\n\n"
            )

        url = f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": Config.TELEGRAM_CHANNEL_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": False
        }

        try:
            response = requests.post(url, json=payload, timeout=float(Config.REQUEST_TIMEOUT))
            if response.ok:
                logger.info(f"Notification sent for {len(products_to_notify)} products")
                return True
            logger.error(f"Telegram API error: {response.status_code}")
            return False
        except Exception as e:
            logger.error(f"Failed to send Telegram notification: {e}")
            return False


# === Product Availability Checker ===
class ProductAvailabilityChecker:
    def __init__(self) -> None:
        self.api_client = AmulAPIClient()
        self.notifier = TelegramNotifier()

    def _create_product_objects(self, raw_products: List[Dict[str, Any]], store: str) -> List[Product]:
        """Convert raw API data to Product objects."""
        return [
            Product(
                alias=product.get('alias', ''),
                name=product.get('name', 'Unknown Product'),
                available=product.get('available', 0) > 0,
                url=f"https://shop.amul.com/product/{product.get('alias', '')}",
                store=store
            )
            for product in raw_products
        ]

    def check_availability(self) -> Tuple[List[Product], List[Product]]:
        """Check product availability and return (available, unavailable) products."""
        if Config.PINCODE is None:
            logger.error("PINCODE is not set")
            return [], []

        store = self.api_client.get_store_from_pincode(Config.PINCODE)
        if not self.api_client.set_store_preferences(store):
            logger.error("Failed to set store preferences")
            return [], []

        raw_products = self.api_client.get_products()
        if not raw_products:
            logger.error("No products retrieved from API")
            return [], []

        products = self._create_product_objects(raw_products, store)
        available = [p for p in products if p.available]
        unavailable = [p for p in products if not p.available]

        return available, unavailable

    def run(self) -> None:
        """Main workflow to check products and notify if available."""
        available_products, unavailable_products = self.check_availability()
        all_products = available_products + unavailable_products

        if Config.FORCE_NOTIFY:
            logger.info(f"Force notify enabled. Sending status for all {len(all_products)} products")
            self.notifier.send_notification(all_products, force=True)
        elif available_products:
            logger.info(f"Found {len(available_products)} available products")
            self.notifier.send_notification(available_products)

        for product in unavailable_products:
            logger.info(f"Product unavailable: {product.name}")


# === Main Execution ===
if __name__ == "__main__":
    checker = ProductAvailabilityChecker()
    checker.run()
