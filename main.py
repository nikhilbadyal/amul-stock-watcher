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
    PINCODE: Optional[str] = os.getenv('PINCODE','110001')
    DEFAULT_STORE: str = os.getenv('DEFAULT_STORE','delhi')
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
    inventory_quantity: int = 0
    weight: int = 0  # in grams
    product_type: str = ""
    inventory_low_stock_quantity: int = 0
    total_order_count: int = 0
    compare_price: float = 0.0
    uom: str = ""  # unit of measurement

    def __str__(self) -> str:
        inventory_info = f" (Stock: {self.inventory_quantity})" if self.inventory_quantity > 0 else ""
        return f"{self.name} ({'Available' if self.available else 'Unavailable'}){inventory_info} - {self.store} - ₹{self.price}"

    def to_telegram_string(self) -> str:
        status = "✅ Available" if self.available else "❌ Unavailable"
        inventory_info = f"  Stock: {self.inventory_quantity} units\n" if self.inventory_quantity > 0 else ""



        # Weight and unit
        weight_info = ""
        if self.weight > 0:
            if self.weight >= 1000:
                weight_kg = self.weight / 1000
                weight_info = f"  Weight: {weight_kg:.1f} kg\n"
            else:
                weight_info = f"  Weight: {self.weight}g\n"

        # Low stock warning
        low_stock_warning = ""
        if (self.available and self.inventory_quantity > 0 and
            self.inventory_low_stock_quantity > 0 and
            self.inventory_quantity <= self.inventory_low_stock_quantity):
            low_stock_warning = "  ⚠️ Low Stock!\n"

        # Product type badge
        type_badge = ""
        if self.product_type:
            if self.product_type.lower() == "bestseller":
                type_badge = "  🏆 Bestseller\n"
            elif self.product_type.lower() == "new":
                type_badge = "  🆕 New Product\n"

        # Popularity indicator
        popularity_info = ""
        if self.total_order_count > 10000:
            popularity_info = f"  🔥 Popular ({self.total_order_count:,} orders)\n"

        # Discount info
        discount_info = ""
        if self.compare_price > self.price:
            discount_amount = self.compare_price - self.price
            discount_pct = (discount_amount / self.compare_price) * 100
            discount_info = f"  💰 Save ₹{discount_amount:.0f} ({discount_pct:.0f}% off)\n"

        return (
            f"• {self.name}\n"
            f"  Status: {status}\n"
            f"  Price: ₹{self.price}\n"
            f"{discount_info}"
            f"{inventory_info}"
            f"{low_stock_warning}"
            f"{weight_info}"
            f"{type_badge}"
            f"{popularity_info}"
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
        # First request to homepage to get Cloudflare cookies
        self.session.get("https://shop.amul.com")

    def _make_request(self, method: str, url: str, **kwargs: Any) -> Optional[Dict[str, Any]]:
        """Generic request handler with error handling.

        Handles:
        - JSON responses (returns parsed dict)
        - Plain text success responses (returns {"status": "success"})
        - All other cases (returns None)
        """
        response = self.session.request(
            method,
            url,
            timeout=float(Config.REQUEST_TIMEOUT),
            **kwargs
        )
        response.raise_for_status()

        # First try to parse as JSON
        try:
            return response.json()  # type:ignore[no-any-return]
        except ValueError:
            # If not JSON, check for plain text success message
            if response.text.strip().lower() in ("updated successfully", "ok", "success"):
                return {"status": "success"}

            # For other plain text responses, return the text in a structured way
            return {"text_response": response.text.strip()}

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

    def get_product_details(self, alias: str) -> Optional[Dict[str, Any]]:
        """Fetch detailed product information including inventory for a specific product alias."""
        url = "https://shop.amul.com/api/1/entity/ms.products"
        params = {
            "q": json.dumps({"alias": alias}),
            "limit": 1
        }

        logger.debug(f"Fetching detailed info for product: {alias}")
        data = self._make_request("GET", url, params=params)
        if data and data.get('data') and len(data['data']) > 0:
            return data['data'][0]  # type:ignore[no-any-return]
        return None

    def get_store_from_pincode(self, pincode: str) -> str:
        """Get store name from pincode API."""
        url = "https://shop.amul.com/entity/pincode"
        params = {
            "limit": 50,
            "filters[0][field]": "pincode",
            "filters[0][value]": pincode,
            "filters[0][operator]": "regex",
            "cf_cache":"1h"
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
    def send_notification(products: List[Product], force: bool = False, log_to_console: bool = False) -> bool:
        """Send consolidated product availability notification via Telegram.

        Args:
            products: List of products to notify about
            force: If True, send notification regardless of availability status
            log_to_console: If True, print notification to terminal instead of sending
        """
        if not all([Config.TELEGRAM_BOT_TOKEN, Config.TELEGRAM_CHANNEL_ID]):
            log_to_console = True  # Force dry run if credentials are missing
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
            message += product.to_telegram_string() + "\n"

        # Add cool footer
        message += (
            "─" * 25 + "\n"
            "🚀 Find more cool projects at:\n"
            "👨‍💻 https://github.com/nikhilbadyal\n"
            "⭐ Star if you found this useful!"
        )

        # Handle dry run mode
        if log_to_console:
            print("\n" + "=" * 50)
            print("DRY RUN - Telegram Notification Preview:")
            print("=" * 50)
            print(message)
            print("=" * 50)
            logger.info(f"DRY RUN: Would notify about {len(products_to_notify)} products")
            return True

        # Normal Telegram sending logic
        if not all([Config.TELEGRAM_BOT_TOKEN, Config.TELEGRAM_CHANNEL_ID]):
            logger.error("Telegram credentials are not set.")
            return False

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
        """Convert raw API data to Product objects with detailed inventory information."""
        products = []

        for product in raw_products:
            alias = product.get('alias', '')
            # Get detailed product information including inventory
            detailed_info = self.api_client.get_product_details(alias)

            # Default values
            inventory_quantity = 0
            weight = 0
            product_type = ""
            inventory_low_stock_quantity = 0
            total_order_count = 0
            compare_price = 0.0
            uom = ""

            if detailed_info:
                inventory_quantity = int(detailed_info.get('inventory_quantity', 0))
                weight = int(detailed_info.get('weight', 0))
                inventory_low_stock_quantity = int(detailed_info.get('inventory_low_stock_quantity', 0))
                total_order_count = int(detailed_info.get('total_order_count', 0))
                compare_price = float(detailed_info.get('compare_price', 0.0))

                # Extract product type from metafields
                metafields = detailed_info.get('metafields', {})
                if metafields:
                    product_type = str(metafields.get('product_type', ''))
                    uom = str(metafields.get('uom', ''))
            else:
                logger.warning(f"Could not fetch detailed info for product: {alias}")

            product_obj = Product(
                alias=alias,
                name=product.get('name', 'Unknown Product'),
                available=product.get('available', 0) > 0,
                url=f"https://shop.amul.com/product/{alias}",
                store=store,
                price=float(product.get('price', 0)),
                inventory_quantity=inventory_quantity,
                weight=weight,
                product_type=product_type,
                inventory_low_stock_quantity=inventory_low_stock_quantity,
                total_order_count=total_order_count,
                compare_price=compare_price,
                uom=uom
            )
            products.append(product_obj)

        return products

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

    def run(self, force_notify: Optional[bool] = None, dry_run: bool = False) -> None:
        """Main workflow to check products and notify if newly available."""
        available_products, unavailable_products = self.check_availability()
        all_products = available_products + unavailable_products

        # Use CLI argument if provided, otherwise fall back to config
        should_force_notify = force_notify if force_notify is not None else Config.FORCE_NOTIFY

        if should_force_notify:
            logger.info(f"Force notify enabled. Sending status for all {len(all_products)} products")
            self.notifier.send_notification(all_products, force=True, log_to_console=dry_run)
        else:
            if self.use_state_management and self.state_manager:
                # Only notify for newly available products (not previously available)
                newly_available = self.state_manager.get_newly_available_products(all_products)

                if newly_available:
                    logger.info(f"Found {len(newly_available)} newly available products")
                    self.notifier.send_notification(newly_available, log_to_console=dry_run)
                else:
                    logger.info("No newly available products to notify about")
            else:
                # Fallback to basic notification when Redis is not available
                if available_products:
                    logger.info(f"Redis not available - sending basic notification for {len(available_products)} available products")
                    self.notifier.send_notification(available_products, log_to_console=dry_run)
                else:
                    logger.info("No available products to notify about")

        # Log current status
        logger.info(f"Current status - Available: {len(available_products)}, Unavailable: {len(unavailable_products)}")
        for product in unavailable_products:
            logger.debug(f"Product unavailable: {product.name}")


# === Main Execution ===
@click.command()
@click.option('--force', is_flag=True, help='Force send notification for all products regardless of availability status')
@click.option('--dry-run', is_flag=True, help='Print notification to terminal instead of sending to Telegram')
def main(force: bool, dry_run: bool) -> None:
    """Check Amul product availability and send notifications."""
    if dry_run:
        logger.info("DRY RUN mode enabled - notifications will be printed to terminal")

    checker = ProductAvailabilityChecker()
    checker.run(force_notify=force, dry_run=dry_run)


if __name__ == "__main__":
    main()
