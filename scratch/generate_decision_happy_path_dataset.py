#!/usr/bin/env python3
"""Generate a large, deterministic CSV that exercises the decision happy path.

The transaction patterns remain identical to the balanced E2E fixture.  This
variant adds an explicit, traceable inventory snapshot for every SKU, allowing
the capital gate to produce financial scenarios without treating an order-row
stock value as verified inventory evidence.
"""

from __future__ import annotations

import csv
from pathlib import Path

from generate_large_dataset import REFERENCE_DATE, generate_rows


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_ROOT / 'test-data' / 'e2e_decision_happy_path_1000_skus.csv'
WAREHOUSE_CODE = 'WH-CENTRAL'

HEADERS = [
    'order_id',
    'item_sku',
    'product_name',
    'quantity',
    'price',
    'cost',
    'stock',
    'order_date',
    'inventory_as_of_date',
    'inventory_snapshot_id',
    'warehouse_code',
    'lifecycle_status',
]


def main() -> None:
    rows = generate_rows()
    as_of = REFERENCE_DATE.isoformat()
    for row in rows:
        sku = str(row['item_sku'])
        row.update({
            'inventory_as_of_date': as_of,
            'inventory_snapshot_id': f'CSV-HAPPY-{REFERENCE_DATE:%Y%m%d}-{sku}',
            'warehouse_code': WAREHOUSE_CODE,
            'lifecycle_status': 'ACTIVE',
        })

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open('w', newline='', encoding='utf-8') as output_file:
        writer = csv.DictWriter(output_file, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)

    print(f'Created {OUTPUT_PATH}')
    print(f'SKUs: 1,000; transaction rows: {len(rows):,}; explicit inventory snapshots: 1,000')


if __name__ == '__main__':
    main()
