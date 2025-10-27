"""Selenium-based client for fetching Amul product data."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Set, Tuple

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

from .config import Config

logger = logging.getLogger(__name__)


# noinspection PyBroadException
def get_api_requests(
    driver: webdriver.Chrome, endpoint_filter: Optional[str] = None
) -> List[Tuple[str, str]]:
    logs = driver.get_log("performance")
    api_requests: List[Tuple[str, str]] = []
    seen_urls: Set[str] = set()
    for entry in logs:
        try:
            message = json.loads(entry["message"])
            method = message["message"]["method"]
            params = message["message"]["params"]
            if method == "Network.responseReceived":
                url = params["response"].get("url", "")
                if url.startswith("https://shop.amul.com/api/"):
                    if (
                        endpoint_filter is None or endpoint_filter in url
                    ) and url not in seen_urls:
                        api_requests.append((params["requestId"], url))
                        seen_urls.add(url)
        except Exception:
            continue
    return api_requests


def get_response_body(
    driver: webdriver.Chrome, request_id: str
) -> Optional[Dict[str, Any]]:
    # noinspection PyBroadException
    try:
        result = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": request_id})
        if "body" in result:
            return result  # type: ignore[no-any-return]
        return None
    except Exception:
        return None


class AmulAPIClient:
    """High-level interface for Amul storefront interactions."""

    def __init__(self) -> None:
        self.driver = self._create_driver()
        self.wait = WebDriverWait(self.driver, 10)
        self.driver.get("https://shop.amul.com/en/")
        time.sleep(0.5)
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
        chrome_options.add_argument("--disable-web-security")
        chrome_options.add_argument("--disable-features=TranslateUI")
        chrome_options.add_argument("--disable-ipc-flooding-protection")
        chrome_options.add_argument("--disable-hang-monitor")
        chrome_options.add_argument("--disable-client-side-phishing-detection")
        chrome_options.add_argument("--disable-popup-blocking")
        chrome_options.add_argument("--disable-prompt-on-repost")
        chrome_options.add_argument("--disable-sync")
        chrome_options.add_argument("--metrics-recording-only")
        chrome_options.add_argument("--no-first-run")
        chrome_options.add_argument("--safebrowsing-disable-auto-update")
        chrome_options.add_argument("--disable-background-networking")
        chrome_options.add_argument("--disable-default-apps")
        chrome_options.add_argument("--disable-component-extensions-with-background-pages")
        chrome_options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

        if os.getenv("CHROME_NO_SANDBOX"):
            chrome_options.add_argument("--no-sandbox")
        if os.getenv("CHROME_DISABLE_GPU"):
            chrome_options.add_argument("--disable-gpu")

        driver = webdriver.Chrome(service=ChromeService(), options=chrome_options)
        driver.execute_cdp_cmd("Network.enable", {})
        return driver

    def _get_driver_from_pool(self) -> webdriver.Chrome:
        """Get a WebDriver instance from the pool or create a new one."""
        with self._driver_pool_lock:
            if self._driver_pool:
                return self._driver_pool.pop()
            return self._create_driver()

    def _return_driver_to_pool(self, driver: webdriver.Chrome) -> None:
        """Return a WebDriver instance to the pool."""
        with self._driver_pool_lock:
            self._driver_pool.append(driver)

    # noinspection PyBroadException
    def __del__(self) -> None:
        try:
            self.driver.quit()
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
        result_tile = self.wait.until(ec.element_to_be_clickable((By.CSS_SELECTOR, result_selector)))
        result_tile.click()
        self.wait.until(
            ec.invisibility_of_element_located((By.CSS_SELECTOR, 'input[placeholder="Enter Your Pincode"]'))
        )
        confirmation = self.wait.until(
            ec.visibility_of_element_located((By.CSS_SELECTOR, "div.pincode_wrap span.ms-2.fw-semibold"))
        )
        logger.info("✅ Pin code confirmed: %s", confirmation.text)
        return True

    def get_products(self) -> List[Dict[str, Any]]:
        protein_url = "https://shop.amul.com/en/browse/protein"
        self.driver.get(protein_url)
        time.sleep(2)
        api_requests = get_api_requests(self.driver, endpoint_filter="ms.products")
        for request_id, url in api_requests:
            if 'filters[0][field]=categories' in url:
                body = get_response_body(self.driver, request_id)
                if body and "body" in body:
                    json_data = json.loads(body["body"])
                    product_list = json_data.get("data", [])
                    logger.info("Found %s protein products.", len(product_list))
                    return product_list  # type: ignore[no-any-return]
        logger.error("Could not find products data.")
        return []

    def get_product_details(self, alias: str) -> Optional[Dict[str, Any]]:
        """Get product details using the main driver instance."""
        return self._get_product_details_with_driver(alias, self.driver)

    def _get_product_details_with_driver(
        self, alias: str, driver: webdriver.Chrome
    ) -> Optional[Dict[str, Any]]:
        """Get product details using a specific WebDriver instance."""
        product_url = f"https://shop.amul.com/en/product/{alias}"
        driver.get(product_url)
        time.sleep(0.8)
        api_requests = get_api_requests(driver, endpoint_filter="ms.products")
        for request_id, url in api_requests:
            if f'"alias":"{alias}"' in url or alias in url:
                body = get_response_body(driver, request_id)
                if body and "body" in body:
                    try:
                        data: Dict[str, Any] = json.loads(body["body"])
                        return data
                    except Exception as exc:
                        logger.warning("JSON decode error for %s: %s", alias, exc)
                break
        logger.warning("Could not fetch detailed info for product: %s", alias)
        return None

    def get_product_details_parallel(
        self, aliases: List[str], max_workers: int = 4
    ) -> Dict[str, Optional[Dict[str, Any]]]:
        """Get product details for multiple aliases in parallel."""
        results: Dict[str, Optional[Dict[str, Any]]] = {}

        def fetch_single_product(alias: str) -> Tuple[str, Optional[Dict[str, Any]]]:
            driver = self._get_driver_from_pool()
            try:
                return alias, self._get_product_details_with_driver(alias, driver)
            finally:
                self._return_driver_to_pool(driver)

        logger.info("Fetching detailed info for %s products using %s workers", len(aliases), max_workers)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_alias = {executor.submit(fetch_single_product, alias): alias for alias in aliases}
            for future in as_completed(future_to_alias):
                alias, result = future.result()
                results[alias] = result
                logger.debug("Completed fetching details for: %s", alias)

        logger.info(
            "Successfully fetched details for %s/%s products",
            len([r for r in results.values() if r is not None]),
            len(aliases),
        )
        return results

    def get_store_from_pincode(self, _: str) -> str:
        return ""
