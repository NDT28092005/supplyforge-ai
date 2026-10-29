#!/usr/bin/env python3
"""Create a deterministic, balanced CSV for SupplyForge end-to-end testing.

The generated file deliberately contains only the eight columns accepted by the
CSV import flow. Its risk segment is encoded in the SKU prefix, rather than an
input label column, so the import and assessment flow cannot read the answer.
"""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_ROOT / "test-data" / "e2e_balanced_risk_1000_skus.csv"
REFERENCE_DATE = date(2026, 10, 29)
SKUS_PER_SEGMENT = 250
RANDOM_SEED = 20261029

HEADERS = [
    "order_id",
    "item_sku",
    "product_name",
    "quantity",
    "price",
    "cost",
    "stock",
    "order_date",
]

CATEGORIES = (
    "Thời trang",
    "Điện tử tiêu dùng",
    "Nhà cửa và đời sống",
    "Chăm sóc cá nhân",
    "Mẹ và bé",
)


@dataclass(frozen=True)
class Segment:
    name: str
    prefix: str
    product_label: str
    stock_base: int
    cost_base: int


SEGMENTS = (
    Segment("CRITICAL", "E2E-CRIT", "Danh mục cần xử lý khẩn", 340, 280_000),
    Segment("HIGH_RISK", "E2E-HIGH", "Danh mục cần ưu tiên rà soát", 220, 190_000),
    Segment("MEDIUM_RISK", "E2E-MED", "Danh mục cần theo dõi", 130, 120_000),
    Segment("LOW_RISK", "E2E-LOW", "Danh mục vận hành ổn định", 65, 75_000),
)


def sales_days_ago(segment: str, sku_index: int) -> list[int]:
    """Return distinct transaction days with one clear historical pattern per tier."""
    if segment == "CRITICAL":
        # No sale in the most recent 90 days.
        return [95 + sku_index % 7, 125 + sku_index % 11, 165 + sku_index % 13]
    if segment == "HIGH_RISK":
        # Fifteen low-volume sale days, with the last sale 45-48 days ago.
        # The oldest transaction still falls within the 90-day window.
        last_sale_days = 45 + sku_index % 4
        return [last_sale_days + offset for offset in range(0, 45, 3)]
    if segment == "MEDIUM_RISK":
        # Twenty-four moderate-frequency sale days, last sale 18-21 days ago.
        # The oldest transaction still falls within the 90-day window.
        last_sale_days = 18 + sku_index % 4
        return [last_sale_days + offset for offset in range(0, 72, 3)]
    if segment == "LOW_RISK":
        # Forty-five regular sale days in the latest 90-day observation window.
        last_sale_days = sku_index % 2
        return [last_sale_days + offset for offset in range(0, 90, 2)]
    raise ValueError(f"Unsupported segment: {segment}")


def quantity_for(segment: str) -> int:
    return 2 if segment == "LOW_RISK" else 1


def generate_rows() -> list[dict[str, object]]:
    randomizer = random.Random(RANDOM_SEED)
    rows: list[dict[str, object]] = []
    order_number = 1

    for segment in SEGMENTS:
        for sku_index in range(1, SKUS_PER_SEGMENT + 1):
            sku = f"{segment.prefix}-{sku_index:04d}"
            category = CATEGORIES[(sku_index - 1) % len(CATEGORIES)]
            product_name = f"{segment.product_label} | {category} | Mẫu {sku_index:04d}"
            cost = segment.cost_base + sku_index * 700 + randomizer.randrange(0, 8_000, 500)
            price = int(round(cost * (1.28 + (sku_index % 5) * 0.02), -2))
            stock = segment.stock_base + (sku_index % 70) * 3
            quantity = quantity_for(segment.name)

            for days_ago in sales_days_ago(segment.name, sku_index):
                rows.append(
                    {
                        "order_id": f"E2E-ORD-{order_number:07d}",
                        "item_sku": sku,
                        "product_name": product_name,
                        "quantity": quantity,
                        "price": price,
                        "cost": cost,
                        "stock": stock,
                        "order_date": (REFERENCE_DATE - timedelta(days=days_ago)).isoformat(),
                    }
                )
                order_number += 1

    return sorted(rows, key=lambda row: (str(row["order_date"]), str(row["order_id"])))


def main() -> None:
    rows = generate_rows()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Created {OUTPUT_PATH}")
    print(f"SKUs: {SKUS_PER_SEGMENT * len(SEGMENTS):,}; transaction rows: {len(rows):,}")
    for segment in SEGMENTS:
        rows_for_segment = sum(1 for row in rows if str(row["item_sku"]).startswith(segment.prefix))
        print(f"{segment.name}: {SKUS_PER_SEGMENT} SKUs, {rows_for_segment:,} rows")


if __name__ == "__main__":
    main()
