"""Domain models used by the application."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Product:
    alias: str
    name: str
    available: bool
    url: str
    store: str
    price: float
    inventory_quantity: int = 0
    weight: int = 0
    product_type: str = ""
    inventory_low_stock_quantity: int = 0
    total_order_count: int = 0
    compare_price: float = 0.0
    uom: str = ""

    def __str__(self) -> str:
        inventory_info = (
            f" (Stock: {self.inventory_quantity})" if self.inventory_quantity > 0 else ""
        )
        status = "Available" if self.available else "Unavailable"
        return f"{self.name} ({status}){inventory_info} - {self.store} - ₹{self.price}"

    def to_telegram_string(self) -> str:
        status = "✅ Available" if self.available else "❌ Unavailable"
        inventory_info = (
            f"  Stock: {self.inventory_quantity} units\n"
            if self.inventory_quantity > 0
            else ""
        )
        weight_info = ""
        if self.weight > 0:
            if self.weight >= 1000:
                weight_kg = self.weight / 1000
                weight_info = f"  Weight: {weight_kg:.1f} kg\n"
            else:
                weight_info = f"  Weight: {self.weight}g\n"

        low_stock_warning = ""
        if (
            self.available
            and self.inventory_quantity > 0
            and self.inventory_low_stock_quantity > 0
            and self.inventory_quantity <= self.inventory_low_stock_quantity
        ):
            low_stock_warning = "  ⚠️ Low Stock!\n"

        type_badge = ""
        if self.product_type:
            product_type_lower = self.product_type.lower()
            if product_type_lower == "bestseller":
                type_badge = "  🏆 Bestseller\n"
            elif product_type_lower == "new":
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
