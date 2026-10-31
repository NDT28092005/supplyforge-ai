"""Deterministic, disposable fixtures shared by ingestion performance tests."""

import csv
from datetime import date, timedelta
from pathlib import Path


LARGE_SHOPEE_HEADERS = (
    'order_id', 'item_sku', 'product_name', 'order_date', 'quantity',
    'selling_price', 'cost', 'stock', 'warehouse', 'category', 'platform',
    'order_status',
)


def create_large_shopee_orders_fixture(directory: str, row_count: int = 50_000) -> str:
    """Create a valid 50k-row sales fixture without committing generated data.

    The fixture spans exactly 181 days, has eight stable SKU/name pairs and
    intentionally leaves the warehouse blank in 5% of rows. That gives both
    profilers a predictable performance-sized input while keeping the repo
    small and every test isolated from a checked-in mutable CSV.
    """
    path = Path(directory) / 'large_shopee_orders_50k.csv'
    start = date(2025, 1, 1)
    with path.open('w', encoding='utf-8', newline='') as output:
        writer = csv.writer(output)
        writer.writerow(LARGE_SHOPEE_HEADERS)
        for index in range(row_count):
            sku_number = (index % 8) + 1
            writer.writerow((
                f'ORD-{index + 1:06d}',
                f'SKU-{sku_number:03d}',
                f'Product {sku_number:03d}',
                (start + timedelta(days=index % 181)).isoformat(),
                (index % 5) + 1,
                100_000 + sku_number * 1_000,
                60_000 + sku_number * 500,
                10 + (index % 20),
                '' if index % 20 == 0 else f'WH-{(index % 3) + 1}',
                f'Category {(sku_number - 1) % 4 + 1}',
                'SHOPEE',
                'COMPLETED',
            ))
    return str(path)
