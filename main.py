import os
import requests
from typing import List, Dict, Optional, Tuple, Any, Union, Set
from dataclasses import dataclass
import logging
from dotenv import load_dotenv
import redis
import click
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.chrome.service import Service as ChromeService
import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()

# === Logging Setup ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class Config:
    TELEGRAM_BOT_TOKEN: Optional[str] = os.getenv('TELEGRAM_BOT_TOKEN')
    TELEGRAM_CHANNEL_ID: Optional[str] = os.getenv('TELEGRAM_CHANNEL_ID')
    PINCODE: Optional[str] = os.getenv('PINCODE', '110001')
    DEFAULT_STORE: str = os.getenv('DEFAULT_STORE', 'delhi')
    REQUEST_TIMEOUT: Union[int, float] = float(os.getenv('REQUEST_TIMEOUT', '3'))
    FORCE_NOTIFY: bool = os.getenv('FORCE_NOTIFY', 'False').lower() == 'true'
    REDIS_HOST: str = os.getenv('REDIS_HOST', 'localhost')
    REDIS_PORT: int = int(os.getenv('REDIS_PORT', '6379'))
    REDIS_DB: int = int(os.getenv('REDIS_DB', '0'))
    REDIS_PASSWORD: Optional[str] = os.getenv('REDIS_PASSWORD')
    REDIS_SSL: bool = os.getenv('REDIS_SSL', 'False').lower() == 'true'
    REDIS_KEY_PREFIX: str = os.getenv('REDIS_KEY_PREFIX', 'amul:')
    MAX_WORKERS: int = int(os.getenv('MAX_WORKERS', '8'))  # Number of parallel workers for fetching product details

HEADERS: Dict[str, str] = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Origin": "https://shop.amul.com",
    "Referer": "https://shop.amul.com/",
}

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
        weight_info = ""
        if self.weight > 0:
            if self.weight >= 1000:
                weight_kg = self.weight / 1000
                weight_info = f"  Weight: {weight_kg:.1f} kg\n"
            else:
                weight_info = f"  Weight: {self.weight}g\n"
        low_stock_warning = ""
        if (self.available and self.inventory_quantity > 0 and
            self.inventory_low_stock_quantity > 0 and
            self.inventory_quantity <= self.inventory_low_stock_quantity):
            low_stock_warning = "  ⚠️ Low Stock!\n"
        type_badge = ""
        if self.product_type:
            if self.product_type.lower() == "bestseller":
                type_badge = "  🏆 Bestseller\n"
            elif self.product_type.lower() == "new":
                type_badge = "  🆕 New Product\n"
        popularity_info = ""
        if self.total_order_count > 10000:
            popularity_info = f"  🔥 Popular ({self.total_order_count:,} orders)\n"
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


# noinspection PyBroadException
def get_api_requests(driver: webdriver.Chrome, endpoint_filter: Optional[str]=None) -> List[Tuple[str, str]]:
    logs = driver.get_log('performance')
    api_requests: List[Tuple[str, str]] = []
    seen_urls: Set[str] = set()
    for entry in logs:
        try:
            message = json.loads(entry['message'])
            method = message['message']['method']
            params = message['message']['params']
            if method == 'Network.responseReceived':
                url = params['response'].get('url', '')
                if url.startswith("https://shop.amul.com/api/"):
                    if (endpoint_filter is None or endpoint_filter in url) and url not in seen_urls:
                        api_requests.append((params['requestId'], url))
                        seen_urls.add(url)
        except Exception:
            continue
    return api_requests

def get_response_body(driver: webdriver.Chrome, request_id: str) -> Optional[Dict[str, Any]]:
    # noinspection PyBroadException
    try:
        result = driver.execute_cdp_cmd('Network.getResponseBody', {'requestId': request_id})
        if 'body' in result:
            return result #type: ignore[no-any-return]
        return None
    except Exception:
        return None

class AmulAPIClient:
    def __init__(self) -> None:
        self.driver = self._create_driver()
        self.wait = WebDriverWait(self.driver, 15)
        self.driver.get("https://shop.amul.com/en/")
        time.sleep(1)  # Reduced initial page load wait time
        self._driver_pool_lock = threading.Lock()
        self._driver_pool: List[webdriver.Chrome] = []

    def _create_driver(self) -> webdriver.Chrome:
        """Create a new Chrome WebDriver instance with optimized settings."""
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-logging")
        chrome_options.add_argument("--disable-default-apps")
        chrome_options.add_argument("--disable-background-timer-throttling")
        chrome_options.add_argument("--disable-backgrounding-occluded-windows")
        chrome_options.add_argument("--disable-renderer-backgrounding")
        chrome_options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
        driver = webdriver.Chrome(service=ChromeService(), options=chrome_options)
        driver.execute_cdp_cmd('Network.enable', {})
        return driver

    def _get_driver_from_pool(self) -> webdriver.Chrome:
        """Get a WebDriver instance from the pool or create a new one."""
        with self._driver_pool_lock:
            if self._driver_pool:
                return self._driver_pool.pop()
            else:
                return self._create_driver()

    def _return_driver_to_pool(self, driver: webdriver.Chrome) -> None:
        """Return a WebDriver instance to the pool."""
        with self._driver_pool_lock:
            self._driver_pool.append(driver)

    # noinspection PyBroadException
    def __del__(self) -> None:
        try:
            self.driver.quit()
            # Clean up driver pool
            with self._driver_pool_lock:
                for driver in self._driver_pool:
                    try:
                        driver.quit()
                    except Exception:
                        pass
        except Exception:
            pass

    def set_store_preferences(self, _: str) -> bool:
        input_box = self.wait.until(
            ec.visibility_of_element_located((By.CSS_SELECTOR, 'input[placeholder="Enter Your Pincode"]'))
        )
        input_box.clear()
        input_box.send_keys(Config.PINCODE)
        result_selector = 'div.list-group-item.text-left.searchproduct-name a.searchitem-name'
        result_tile = self.wait.until(
            ec.element_to_be_clickable((By.CSS_SELECTOR, result_selector))
        )
        result_tile.click()
        self.wait.until(
            ec.invisibility_of_element_located((By.CSS_SELECTOR, 'input[placeholder="Enter Your Pincode"]'))
        )
        confirmation = self.wait.until(
            ec.visibility_of_element_located((By.CSS_SELECTOR, 'div.pincode_wrap span.ms-2.fw-semibold'))
        )
        logger.info("✅ Pin code confirmed: %s", confirmation.text)
        return True

    def get_products(self) -> List[Dict[str, Any]]:
        protein_url = "https://shop.amul.com/en/browse/protein"
        self.driver.get(protein_url)
        time.sleep(2)  # Reduced from 5 to 2 seconds
        api_requests = get_api_requests(self.driver, endpoint_filter="ms.products")
        for request_id, url in api_requests:
            if "filters[0][field]=categories" in url:
                body = get_response_body(self.driver, request_id)
                if body and 'body' in body:
                    json_data = json.loads(body['body'])
                    product_list = json_data.get('data', [])
                    logger.info(f"Found {len(product_list)} protein products.")
                    return product_list #type: ignore[no-any-return]
        logger.error("Could not find products data.")
        return []

    def get_product_details(self, alias: str) -> Optional[Dict[str, Any]]:
        """Get product details using the main driver instance (for backward compatibility)."""
        return self._get_product_details_with_driver(alias, self.driver)

    def _get_product_details_with_driver(self, alias: str, driver: webdriver.Chrome) -> Optional[Dict[str, Any]]:
        """Get product details using a specific WebDriver instance."""
        product_url = f"https://shop.amul.com/en/product/{alias}"
        driver.get(product_url)
        time.sleep(1.5)  # Reduced sleep time for better performance
        api_requests = get_api_requests(driver, endpoint_filter="ms.products")
        for request_id, url in api_requests:
            if f'"alias":"{alias}"' in url or alias in url:
                body = get_response_body(driver, request_id)
                if body and 'body' in body:
                    try:
                        data: Dict[str, Any] = json.loads(body['body'])
                        return data
                    except Exception as e:
                        logger.warning(f"JSON decode error for {alias}: {e}")
                break
        logger.warning(f"Could not fetch detailed info for product: {alias}")
        return None

    def get_product_details_parallel(self, aliases: List[str], max_workers: int = 4) -> Dict[str, Optional[Dict[str, Any]]]:
        """Get product details for multiple aliases in parallel."""
        results: Dict[str, Optional[Dict[str, Any]]] = {}

        def fetch_single_product(alias: str) -> Tuple[str, Optional[Dict[str, Any]]]:
            driver = self._get_driver_from_pool()
            try:
                result = self._get_product_details_with_driver(alias, driver)
                return alias, result
            finally:
                self._return_driver_to_pool(driver)

        logger.info(f"Fetching detailed info for {len(aliases)} products using {max_workers} workers")
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_alias = {executor.submit(fetch_single_product, alias): alias for alias in aliases}

            # Process completed tasks
            for future in as_completed(future_to_alias):
                alias, result = future.result()
                results[alias] = result
                logger.debug(f"Completed fetching details for: {alias}")

        logger.info(f"Successfully fetched details for {len([r for r in results.values() if r is not None])}/{len(aliases)} products")
        return results

    def get_store_from_pincode(self, _: str) -> str:
        return ""

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
            self.redis_client.ping()
            logger.info("Connected to Redis successfully")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    def get_previous_state(self, store: str) -> Set[str]:
        key = f"{Config.REDIS_KEY_PREFIX}{store}:available"
        try:
            aliases = self.redis_client.smembers(key)
            return set(aliases) if aliases else set()
        except Exception as e:
            logger.error(f"Failed to get previous state from Redis: {e}")
            return set()

    def update_state(self, store: str, available_aliases: Set[str]) -> bool:
        key = f"{Config.REDIS_KEY_PREFIX}{store}:available"
        try:
            self.redis_client.delete(key)
            if available_aliases:
                self.redis_client.sadd(key, *available_aliases)
            self.redis_client.expire(key, 7 * 24 * 60 * 60)
            return True
        except Exception as e:
            logger.error(f"Failed to update state in Redis: {e}")
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
            p for p in current_products
            if p.available and p.alias in newly_available_aliases
        ]
        logger.info(f"Previous available: {len(previous_available)}, Current available: {len(current_available)}, Newly available: {len(newly_available_products)}")
        return newly_available_products

class TelegramNotifier:
    @staticmethod
    def send_notification(products: List[Product], force: bool = False, log_to_console: bool = False) -> bool:
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
            "─" * 25 + "\n"
            "🚀 Find more cool projects at:\n"
            "👨‍💻 https://github.com/nikhilbadyal\n"
            "⭐ Star if you found this useful!"
        )
        if log_to_console:
            print("\n" + "=" * 50)
            print("DRY RUN - Telegram Notification Preview:")
            print("=" * 50)
            print(message)
            print("=" * 50)
            logger.info(f"DRY RUN: Would notify about {len(products_to_notify)} products")
            return True
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

class ProductAvailabilityChecker:
    def __init__(self) -> None:
        self.api_client = AmulAPIClient()
        self.notifier = TelegramNotifier()
        self.state_manager: Optional[RedisStateManager]
        try:
            self.state_manager = RedisStateManager()
            self.use_state_management = True
        except Exception as e:
            logger.warning(f"Redis not available, falling back to basic notification: {e}")
            self.state_manager = None
            self.use_state_management = False

    def _create_product_objects(self, raw_products: List[Dict[str, Any]], store: str) -> List[Product]:
        products: List[Product] = []

        # Extract aliases for parallel fetching
        aliases = [product.get('alias', '') for product in raw_products if product.get('alias')]

        # Fetch detailed info for all products in parallel
        detailed_info_map = self.api_client.get_product_details_parallel(aliases, max_workers=Config.MAX_WORKERS)

        # Create product objects with detailed info
        for product in raw_products:
            alias = product.get('alias', '')
            detailed_info = detailed_info_map.get(alias)

            # Extract detailed information
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
                metafields = detailed_info.get('metafields', {})
                if metafields:
                    product_type = str(metafields.get('product_type', ''))
                    uom = str(metafields.get('uom', ''))

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
        if Config.PINCODE is None:
            raise ValueError("PINCODE must be set in the environment variables")
        store = self.api_client.get_store_from_pincode(Config.PINCODE) if Config.PINCODE else Config.DEFAULT_STORE
        self.api_client.set_store_preferences(store)
        raw_products = self.api_client.get_products()
        if not raw_products:
            raise ValueError("No products found in the API response")
        else:
            logger.info(f"Retrieved {len(raw_products)} products from API for store: {store}")
        products = self._create_product_objects(raw_products, store)
        available = [p for p in products if p.available]
        unavailable = [p for p in products if not p.available]
        return available, unavailable

    def _handle_notifications(self, all_products: List[Product], available_products: List[Product], should_force_notify: bool, dry_run: bool) -> None:
        if should_force_notify:
            logger.info(f"Force notify enabled. Sending status for all {len(all_products)} products")
            self.notifier.send_notification(all_products, force=True, log_to_console=dry_run)
        else:
            if self.use_state_management and self.state_manager:
                newly_available = self.state_manager.get_newly_available_products(all_products)
                if newly_available:
                    logger.info(f"Found {len(newly_available)} newly available products")
                    self.notifier.send_notification(newly_available, log_to_console=dry_run)
                else:
                    logger.info("No newly available products to notify about")
            else:
                if available_products:
                    logger.info(f"Redis not available - sending basic notification for {len(available_products)} available products")
                    self.notifier.send_notification(available_products, log_to_console=dry_run)
                else:
                    logger.info("No available products to notify about")

    def run(self, force_notify: Optional[bool] = None, dry_run: bool = False) -> None:
        available_products, unavailable_products = self.check_availability()
        all_products = available_products + unavailable_products
        should_force_notify = force_notify if force_notify is not None else Config.FORCE_NOTIFY
        self._handle_notifications(all_products, available_products, should_force_notify, dry_run)
        logger.info(f"Current status - Available: {len(available_products)}, Unavailable: {len(unavailable_products)}")
        for product in unavailable_products:
            logger.debug(f"Product unavailable: {product.name}")

@click.command()
@click.option('--force', is_flag=True, help='Force send notification for all products regardless of availability status')
@click.option('--dry-run', is_flag=True, help='Print notification to terminal instead of sending to Telegram')
def main(force: bool, dry_run: bool) -> None:
    if dry_run:
        logger.info("DRY RUN mode enabled - notifications will be printed to terminal")
    checker = ProductAvailabilityChecker()
    checker.run(force_notify=force, dry_run=dry_run)

if __name__ == "__main__":
    main()
