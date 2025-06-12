import os
import json
import requests
from typing import List, Dict, Optional, Tuple, Any, Union, Set
from dataclasses import dataclass
import logging
from dotenv import load_dotenv
import redis
import click

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
    REDIS_HOST: str = os.getenv('REDIS_HOST', 'localhost')
    REDIS_PORT: int = int(os.getenv('REDIS_PORT', '6379'))
    REDIS_DB: int = int(os.getenv('REDIS_DB', '0'))
    REDIS_PASSWORD: Optional[str] = os.getenv('REDIS_PASSWORD')
    REDIS_SSL: bool = os.getenv('REDIS_SSL', 'False').lower() == 'true'
    REDIS_KEY_PREFIX: str = os.getenv('REDIS_KEY_PREFIX', 'amul:')


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
    price: float

    def __str__(self) -> str:
        return f"{self.name} ({'Available' if self.available else 'Unavailable'}) - {self.store} - ₹{self.price}"

    def to_telegram_string(self) -> str:
        status = "✅ Available" if self.available else "❌ Unavailable"
        return (
            f"• {self.name}\n"
            f"  Status: {status}\n"
            f"  Price: ₹{self.price}\n"
            f"  Link: {self.url}\n"
        )
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
            "fields[alias]": 1,
            "fields[price]": 1,
            "fields[available]": 1,
            "fields[lp_seller_ids]": 1,
            "filters[0][field]": "categories",
            "filters[0][value][0]": "protein",
            "filters[0][operator]": "in",
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


# === State Management ===
class RedisStateManager:
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
            # Test connection
            self.redis_client.ping()
            logger.info("Connected to Redis successfully")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    def get_previous_state(self, store: str) -> Set[str]:
        """Get previously available product aliases for a store."""
        key = f"{Config.REDIS_KEY_PREFIX}{store}:available"
        try:
            aliases = self.redis_client.smembers(key)
            return set(aliases) if aliases else set()
        except Exception as e:
            logger.error(f"Failed to get previous state from Redis: {e}")
            return set()

    def update_state(self, store: str, available_aliases: Set[str]) -> bool:
        """Update the available products state for a store."""
        key = f"{Config.REDIS_KEY_PREFIX}{store}:available"
        try:
            # Clear existing state
            self.redis_client.delete(key)
            # Set new state if there are available products
            if available_aliases:
                self.redis_client.sadd(key, *available_aliases)
            # Set expiry for 7 days (in case script doesn't run for a while)
            self.redis_client.expire(key, 7 * 24 * 60 * 60)
            return True
        except Exception as e:
            logger.error(f"Failed to update state in Redis: {e}")
            return False

    def get_newly_available_products(self, current_products: List[Product]) -> List[Product]:
        """Compare current state with previous state and return newly available products."""
        if not current_products:
            return []

        store = current_products[0].store  # All products should have same store

        # Get current available products
        current_available = {p.alias for p in current_products if p.available}

        # Get previously available products
        previous_available = self.get_previous_state(store)

        # Find newly available products (in current but not in previous)
        newly_available_aliases = current_available - previous_available

        # Update state with current availability
        self.update_state(store, current_available)

        # Return products that are newly available
        newly_available_products = [
            p for p in current_products
            if p.available and p.alias in newly_available_aliases
        ]

        logger.info(f"Previous available: {len(previous_available)}, Current available: {len(current_available)}, Newly available: {len(newly_available_products)}")

        return newly_available_products


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

        if force:
            message = "📊 Product Status Report\n\n"
        else:
            message = "🎉 New Products Available!\n\n"
        for product in products_to_notify:
            status = "✅ Available" if product.available else "❌ Unavailable"
            message += (
                f"• {product.name}\n"
                f"  Status: {status}\n"
                f"  Price: ₹{product.price}\n"
                f"  Link: {product.url}\n\n"
            )

        # Add cool footer
        message += (
            "─" * 25 + "\n"
            "🚀 Find more cool projects at:\n"
            "👨‍💻 https://github.com/nikhilbadyal\n"
            "⭐ Star if you found this useful!"
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
        try:
            self.state_manager = RedisStateManager()
            self.use_state_management = True
        except Exception as e:
            logger.warning(f"Redis not available, falling back to basic notification: {e}")
            self.state_manager = None # type:ignore[assignment]
            self.use_state_management = False

    def _create_product_objects(self, raw_products: List[Dict[str, Any]], store: str) -> List[Product]:
        """Convert raw API data to Product objects."""
        return [
            Product(
                alias=product.get('alias', ''),
                name=product.get('name', 'Unknown Product'),
                available=product.get('available', 0) > 0,
                url=f"https://shop.amul.com/product/{product.get('alias', '')}",
                store=store,
                price=float(product.get('price', 0))
            )
            for product in raw_products
        ]

    def check_availability(self) -> Tuple[List[Product], List[Product]]:
        """Check product availability and return (available, unavailable) products."""
        if Config.PINCODE is None:
            logger.error("PINCODE is not set")
            return [], []

        store = self.api_client.get_store_from_pincode(Config.PINCODE) if Config.PINCODE else Config.DEFAULT_STORE
        if not self.api_client.set_store_preferences(store):
            logger.error("Failed to set store preferences")
            return [], []

        raw_products = self.api_client.get_products()
        if not raw_products:
            logger.error("No products retrieved from API")
            return [], []
        else:
            logger.info(f"Retrieved {len(raw_products)} products from API for store: {store}")

        products = self._create_product_objects(raw_products, store)
        available = [p for p in products if p.available]
        unavailable = [p for p in products if not p.available]

        return available, unavailable

    def run(self, force_notify: Optional[bool] = None) -> None:
        """Main workflow to check products and notify if newly available."""
        available_products, unavailable_products = self.check_availability()
        all_products = available_products + unavailable_products

        # Use CLI argument if provided, otherwise fall back to config
        should_force_notify = force_notify if force_notify is not None else Config.FORCE_NOTIFY

        if should_force_notify:
            logger.info(f"Force notify enabled. Sending status for all {len(all_products)} products")
            self.notifier.send_notification(all_products, force=True)
        else:
            if self.use_state_management and self.state_manager:
                # Only notify for newly available products (not previously available)
                newly_available = self.state_manager.get_newly_available_products(all_products)

                if newly_available:
                    logger.info(f"Found {len(newly_available)} newly available products")
                    self.notifier.send_notification(newly_available)
                else:
                    logger.info("No newly available products to notify about")
            else:
                # Fallback to basic notification when Redis is not available
                if available_products:
                    logger.info(f"Redis not available - sending basic notification for {len(available_products)} available products")
                    self.notifier.send_notification(available_products)
                else:
                    logger.info("No available products to notify about")

        # Log current status
        logger.info(f"Current status - Available: {len(available_products)}, Unavailable: {len(unavailable_products)}")
        for product in unavailable_products:
            logger.debug(f"Product unavailable: {product.name}")


# === Main Execution ===
@click.command()
@click.option('--force', is_flag=True, help='Force send notification for all products regardless of availability status')
def main(force: bool) -> None:
    """Check Amul product availability and send notifications."""
    checker = ProductAvailabilityChecker()
    checker.run(force_notify=force)


if __name__ == "__main__":
    main()
