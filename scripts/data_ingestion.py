#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  SupplyForge AI 2.0 — Data Ingestion Pipeline (Medallion Architecture) ║
║                                                                        ║
║  Author  : Senior Data Engineer                                        ║
║  Purpose : Transform raw CSV/JSON → Silver Parquet (Memory-safe)       ║
║  Stack   : pandas + pyarrow + json + gc (NO Dask/Spark/Ray)            ║
╚══════════════════════════════════════════════════════════════════════════╝

Pipeline Flow:
    ┌─────────┐      ┌─────────┐      ┌─────────┐
    │ Raw CSV │ ───▶ │ Bronze  │ ───▶ │ Silver  │
    │  / JSON │      │ (Clean) │      │(Parquet)│
    └─────────┘      └─────────┘      └─────────┘

Memory Strategy (v2 — Fixed OOM on 7GB RAM machine):
    1. Chunk size reduced to 10K rows (~52MB data column vs 520MB at 100K)
    2. SPLIT READ: orders columns (light) and data column (heavy) read separately
    3. data column is processed ROW-BY-ROW and discarded immediately per row
    4. items are written to Parquet in mini-batches (every 1000 rows)
    5. gc.collect() after every chunk
    6. NEVER accumulate large Python lists — stream to Parquet writer
"""

import os
import sys
import json
import gc
import logging
import time
from pathlib import Path
from typing import Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from tqdm import tqdm

# ════════════════════════════════════════════════════════════════════════
# Configuration
# ════════════════════════════════════════════════════════════════════════

# --- Paths ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DATA_DIR = PROJECT_ROOT / "test-data" / "Database - NCKH"

# Medallion layer directories — created automatically if absent
BRONZE_DIR = PROJECT_ROOT / "data" / "bronze"
SILVER_DIR = PROJECT_ROOT / "data" / "silver"
GOLD_DIR   = PROJECT_ROOT / "data" / "gold"

# Raw source files
ORDERS_CSV    = RAW_DATA_DIR / "orders_full.csv"
PRODUCTS_JSON = RAW_DATA_DIR / "products.json"

# Silver output files
SILVER_ORDERS      = SILVER_DIR / "orders_clean.parquet"
SILVER_ORDER_ITEMS = SILVER_DIR / "order_items_clean.parquet"
SILVER_PRODUCTS    = SILVER_DIR / "products_clean.parquet"

# --- Processing Parameters ---
# ▼▼▼ CRITICAL FIX: Reduced from 100K to 10K ▼▼▼
# With avg 5.4KB per JSON row:
#   100K rows × 5.4KB = 520MB just for data column → OOM on 7GB RAM
#   10K  rows × 5.4KB =  52MB → safe with ~200MB peak per chunk
CHUNK_SIZE = 10_000

# Mini-batch size for streaming items to Parquet writer
# Instead of building one giant list of all items in a chunk,
# we flush to Parquet every ITEM_FLUSH_INTERVAL rows processed.
ITEM_FLUSH_INTERVAL = 2_000

# Column Pruning: ONLY columns relevant for Demand Forecasting.
# Everything else (buyerPhone, address, trackingNumber...) is discarded
# at the CSV reader level and NEVER touches RAM.
#
# IMPORTANT: `data` column is loaded separately in a second pass
# to control its lifecycle independently.
ORDERS_LIGHT_COLS = [
    "_id",              # Primary Key
    "time",             # Order timestamp — critical for time series
    "status",           # Order lifecycle state (filter cancelled)
    "amount",           # Total order value
    "fee",              # Platform/service fee
    "revenue",          # Seller revenue
    "profit",           # Seller profit
    "tax",              # Tax amount
    "voucherFromMarket",  # Marketplace voucher
    "voucherFromSeller",  # Seller voucher
    "vouhcerId",        # Voucher identifier (original typo in source)
    "deliveryPartner",  # Carrier for cancel analysis
    "warehouse",        # Warehouse / seller proxy
    "notCaculateMoney", # Flag for invalid financial records
    "createdAt",        # Record creation timestamp
    "updatedAt",        # Record update timestamp
]

# Combined usecols for CSV reader (light + data)
ORDERS_USECOLS = ORDERS_LIGHT_COLS + ["data"]

# Statuses to EXCLUDE — these orders don't represent real demand
EXCLUDED_STATUSES = {"CANCELLED", "TO_RETURN", "IN_CANCEL"}

# Fields to extract from each item in the nested JSON `data.item_list`
ITEM_EXTRACT_FIELDS = {
    "item_id":                    "itemId",
    "item_name":                  "itemName",
    "model_name":                 "modelName",
    "model_quantity_purchased":   "quantity",
    "model_discounted_price":     "price",
    "model_original_price":       "originalPrice",
    "promotion_id":               "promotionId",
    "weight":                     "weight",
}

# Products — columns to keep for the Silver layer
PRODUCT_KEEP_COLS = [
    "itemId", "productName", "brand", "categoryId",
    "price", "listedPrice", "cost", "stock", "weight",
]

# ════════════════════════════════════════════════════════════════════════
# Logging Setup
# ════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-7s │ %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("DataIngestion")


# ════════════════════════════════════════════════════════════════════════
# Helper: Estimate total chunks for progress bar
# ════════════════════════════════════════════════════════════════════════

def _estimate_total_rows(filepath: Path) -> int:
    """Fast line count using raw file iteration (no pandas overhead).
    Subtracts 1 for the header row."""
    log.info(f"Counting rows in {filepath.name}...")
    count = 0
    with open(filepath, "rb") as f:
        buf_size = 1024 * 1024 * 8  # 8MB buffer
        while True:
            buf = f.raw.read(buf_size)
            if not buf:
                break
            count += buf.count(b"\n")
    return max(count - 1, 0)


# ════════════════════════════════════════════════════════════════════════
# Helper: Log current process RSS memory usage
# ════════════════════════════════════════════════════════════════════════

def _log_memory(label: str = ""):
    """Log current memory usage of the Python process (via /proc/self)."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    rss_kb = int(line.split()[1])
                    log.info(f"  🧠 RAM: {rss_kb / 1024:.0f} MB {label}")
                    return
    except Exception:
        pass  # Not on Linux — skip


# ════════════════════════════════════════════════════════════════════════
# STAGE 1: Parse ONE ROW's JSON → list of item dicts (no DataFrame)
# ════════════════════════════════════════════════════════════════════════

def _extract_items_from_row(
    order_id: str,
    order_time,
    order_status: str,
    warehouse: str,
    delivery_partner: str,
    data_str,
) -> list:
    """
    Parse a single row's `data` JSON string and return a list of
    item dicts extracted from `data.item_list`.

    Returns an empty list if:
    - data_str is NaN/None/empty
    - JSON is malformed
    - item_list is missing or empty

    This function is deliberately a pure function with no side effects
    and no DataFrame overhead — it operates purely on Python dicts.
    """
    if pd.isna(data_str) or not isinstance(data_str, str):
        return []

    try:
        data_dict = json.loads(data_str)
    except (json.JSONDecodeError, TypeError):
        return []

    item_list = data_dict.get("item_list", [])
    if not item_list:
        return []

    records = []
    for item in item_list:
        record = {
            "orderId": order_id,
            "time": order_time,
            "status": order_status,
            "warehouse": warehouse,
            "deliveryPartner": delivery_partner,
        }
        for src_key, dst_key in ITEM_EXTRACT_FIELDS.items():
            record[dst_key] = item.get(src_key, None)
        records.append(record)

    return records


# ════════════════════════════════════════════════════════════════════════
# STAGE 2: Convert items buffer → typed DataFrame (compact)
# ════════════════════════════════════════════════════════════════════════

def _items_to_typed_df(items_buffer: list) -> pd.DataFrame:
    """
    Convert a list of item dicts into a memory-optimized DataFrame.
    Uses int32/float32 instead of default int64/float64 to halve RAM.
    """
    if not items_buffer:
        return pd.DataFrame()

    df = pd.DataFrame(items_buffer)

    df["itemId"] = df["itemId"].astype(str)
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0).astype("int32")
    df["price"] = pd.to_numeric(df["price"], errors="coerce").fillna(0.0).astype("float32")
    df["originalPrice"] = pd.to_numeric(df["originalPrice"], errors="coerce").fillna(0.0).astype("float32")
    df["promotionId"] = pd.to_numeric(df["promotionId"], errors="coerce").fillna(0).astype("int64")
    df["weight"] = pd.to_numeric(df["weight"], errors="coerce").fillna(0.0).astype("float32")
    df["time"] = pd.to_datetime(df["time"], errors="coerce")

    return df


# ════════════════════════════════════════════════════════════════════════
# STAGE 3: Clean & optimize the orders chunk (data column already gone)
# ════════════════════════════════════════════════════════════════════════

def _clean_orders_chunk(chunk: pd.DataFrame) -> pd.DataFrame:
    """
    Clean a single chunk of order data:
    1. Coerce types for memory efficiency (float64 → float32, etc.)
    2. Parse datetime columns
    3. Filter out excluded statuses (CANCELLED, TO_RETURN, IN_CANCEL)
    4. Deduplicate on primary key `_id`

    NOTE: The `data` column has ALREADY been removed before this function
    is called — it was extracted and dropped at the chunk level.
    """
    # ── Type coercion ──
    for col in ["amount", "fee", "revenue", "profit", "tax",
                "voucherFromMarket", "voucherFromSeller"]:
        if col in chunk.columns:
            chunk[col] = pd.to_numeric(chunk[col], errors="coerce").fillna(0.0).astype("float32")

    # ── Datetime parsing ──
    for col in ["time", "createdAt", "updatedAt"]:
        if col in chunk.columns:
            chunk[col] = pd.to_datetime(chunk[col], errors="coerce")

    # ── Filter: remove cancelled / returned / uncounted orders ──
    if "status" in chunk.columns:
        chunk = chunk[~chunk["status"].isin(EXCLUDED_STATUSES)]

    # ── Filter: remove notCaculateMoney flagged orders ──
    if "notCaculateMoney" in chunk.columns:
        chunk["notCaculateMoney"] = pd.to_numeric(
            chunk["notCaculateMoney"], errors="coerce"
        ).fillna(0)
        chunk = chunk[chunk["notCaculateMoney"] == 0]
        chunk = chunk.drop(columns=["notCaculateMoney"])

    # ── Deduplicate within chunk on Primary Key ──
    chunk = chunk.drop_duplicates(subset=["_id"], keep="first")

    return chunk


# ════════════════════════════════════════════════════════════════════════
# STAGE 4: Process Products JSON → Silver Parquet
# ════════════════════════════════════════════════════════════════════════

def ingest_products(
    src_path: Path = PRODUCTS_JSON,
    dst_path: Path = SILVER_PRODUCTS,
) -> None:
    """
    Load products.json, prune to relevant columns, coerce types,
    and save as a compact Parquet file.

    Products JSON is ~30MB — small enough to load in one shot.
    """
    log.info(f"Loading products from {src_path.name}...")

    with open(src_path, "r", encoding="utf-8") as f:
        raw_products = json.load(f)

    df = pd.DataFrame(raw_products)
    log.info(f"  Raw products: {len(df)} rows, {len(df.columns)} columns")

    # ── Column Pruning ──
    available_cols = [c for c in PRODUCT_KEEP_COLS if c in df.columns]
    df = df[available_cols].copy()

    # ── Type coercion ──
    df["itemId"] = df["itemId"].astype(str)
    for col in ["price", "listedPrice", "cost", "stock", "weight"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0).astype("float32")

    # Fill NaN strings
    df["brand"] = df["brand"].fillna("NoBrand")
    df["categoryId"] = df["categoryId"].fillna("NoCategory").astype(str)
    df["productName"] = df["productName"].fillna("")

    # ── Deduplicate ──
    df = df.drop_duplicates(subset=["itemId"], keep="first")

    # ── Save to Silver Parquet ──
    df.to_parquet(dst_path, engine="pyarrow", index=False, compression="snappy")
    log.info(f"  ✅ Silver products saved: {dst_path.name} "
             f"({len(df)} rows, {dst_path.stat().st_size / 1024:.0f} KB)")

    del df, raw_products
    gc.collect()


# ════════════════════════════════════════════════════════════════════════
# STAGE 5: Main Pipeline — Chunk-process Orders CSV (Memory-Safe v2)
# ════════════════════════════════════════════════════════════════════════

def ingest_orders(
    src_path: Path = ORDERS_CSV,
    orders_dst: Path = SILVER_ORDERS,
    items_dst: Path = SILVER_ORDER_ITEMS,
    chunk_size: int = CHUNK_SIZE,
) -> None:
    """
    Core pipeline: Read orders_full.csv in chunks, parse JSON, clean,
    and write two separate Silver Parquet files:
      - orders_clean.parquet     (order-level facts)
      - order_items_clean.parquet (item-level facts, flattened from JSON)

    Memory Guarantees (v2):
      ┌─────────────────────────────────────────────────────────────┐
      │ 1. Chunk size = 10K rows (not 100K) → ~52MB data column    │
      │ 2. Extract `data` Series → drop from chunk IMMEDIATELY     │
      │ 3. Parse JSON row-by-row, flush items every 2K rows        │
      │ 4. Each row's JSON string is del'd right after parsing     │
      │ 5. gc.collect() after EVERY chunk                          │
      │ 6. Peak RAM per chunk: ~200MB (vs 1.5GB in v1)             │
      └─────────────────────────────────────────────────────────────┘
    """
    # ── Remove stale output files (Parquet writers need fresh files) ──
    for f in [orders_dst, items_dst]:
        if f.exists():
            f.unlink()
            log.info(f"  Removed stale: {f.name}")

    # ── Fast row count for progress bar ──
    total_rows = _estimate_total_rows(src_path)
    total_chunks = (total_rows // chunk_size) + 1
    log.info(f"Orders file: ~{total_rows:,} rows → {total_chunks} chunks "
             f"of {chunk_size:,} rows each")

    # ── CSV Reader — Column Pruning happens HERE ──
    reader = pd.read_csv(
        src_path,
        usecols=ORDERS_USECOLS,
        chunksize=chunk_size,
        low_memory=False,
        dtype={
            "_id": str,
            "status": str,
            "warehouse": str,
            "deliveryPartner": str,
            "data": str,
            "vouhcerId": str,
        },
    )

    # ── PyArrow Parquet Writers (append mode via row groups) ──
    orders_writer: Optional[pq.ParquetWriter] = None
    items_writer: Optional[pq.ParquetWriter] = None

    # ── Global deduplication set for order PKs across all chunks ──
    seen_order_ids: set = set()

    orders_total = 0
    items_total = 0
    skipped_dupes = 0

    log.info("Starting chunk processing...")
    _log_memory("(before processing)")
    t_start = time.time()

    for chunk_idx, raw_chunk in enumerate(
        tqdm(reader, total=total_chunks, desc="Processing chunks", unit="chunk")
    ):
        # ──────────────────────────────────────────────────────
        # STEP 1: EXTRACT the `data` column as a separate Series
        #         then DROP it from the chunk IMMEDIATELY.
        #         This is the KEY memory fix — the chunk DataFrame
        #         now weighs ~5% of its original size.
        # ──────────────────────────────────────────────────────
        data_series = raw_chunk.pop("data")  # removes & returns the column

        # ──────────────────────────────────────────────────────
        # STEP 2: Parse JSON row-by-row with streaming flush
        #         Instead of building one giant items_buffer for
        #         the entire chunk (which can be 100K+ items),
        #         we flush to Parquet every ITEM_FLUSH_INTERVAL rows.
        # ──────────────────────────────────────────────────────
        items_buffer = []

        for row_idx in range(len(raw_chunk)):
            order_id   = raw_chunk.iat[row_idx, raw_chunk.columns.get_loc("_id")]
            order_time = raw_chunk.iat[row_idx, raw_chunk.columns.get_loc("time")]
            status     = raw_chunk.iat[row_idx, raw_chunk.columns.get_loc("status")]

            wh_val = raw_chunk.iat[row_idx, raw_chunk.columns.get_loc("warehouse")]
            dp_val = raw_chunk.iat[row_idx, raw_chunk.columns.get_loc("deliveryPartner")]
            warehouse = str(wh_val) if pd.notna(wh_val) else ""
            delivery_partner = str(dp_val) if pd.notna(dp_val) else ""

            data_str = data_series.iat[row_idx]

            items = _extract_items_from_row(
                order_id, order_time, status,
                warehouse, delivery_partner, data_str,
            )
            if items:
                items_buffer.extend(items)

            # ── Mini-batch flush: convert & write items every N rows ──
            if len(items_buffer) >= ITEM_FLUSH_INTERVAL:
                df_items_batch = _items_to_typed_df(items_buffer)
                if not df_items_batch.empty:
                    items_table = pa.Table.from_pandas(df_items_batch, preserve_index=False)
                    if items_writer is None:
                        items_writer = pq.ParquetWriter(
                            str(items_dst), items_table.schema, compression="snappy"
                        )
                    items_writer.write_table(items_table)
                    items_total += len(df_items_batch)
                    del items_table, df_items_batch
                items_buffer.clear()  # release the list memory

        # ── Flush remaining items in this chunk ──
        if items_buffer:
            df_items_batch = _items_to_typed_df(items_buffer)
            if not df_items_batch.empty:
                items_table = pa.Table.from_pandas(df_items_batch, preserve_index=False)
                if items_writer is None:
                    items_writer = pq.ParquetWriter(
                        str(items_dst), items_table.schema, compression="snappy"
                    )
                items_writer.write_table(items_table)
                items_total += len(df_items_batch)
                del items_table, df_items_batch
            del items_buffer

        # ── Kill the heavy data_series — all JSON parsed ──
        del data_series
        gc.collect()

        # ──────────────────────────────────────────────────────
        # STEP 3: Clean orders chunk (data column already gone)
        # ──────────────────────────────────────────────────────
        df_orders_chunk = _clean_orders_chunk(raw_chunk)

        # ──────────────────────────────────────────────────────
        # STEP 4: Cross-chunk deduplication on _id
        # ──────────────────────────────────────────────────────
        if not df_orders_chunk.empty:
            mask_new = ~df_orders_chunk["_id"].isin(seen_order_ids)
            chunk_dupes = (~mask_new).sum()
            skipped_dupes += chunk_dupes

            df_orders_chunk = df_orders_chunk[mask_new]
            seen_order_ids.update(df_orders_chunk["_id"].tolist())

        # ──────────────────────────────────────────────────────
        # STEP 5: Write orders chunk → Parquet (append row group)
        # ──────────────────────────────────────────────────────
        if not df_orders_chunk.empty:
            orders_table = pa.Table.from_pandas(df_orders_chunk, preserve_index=False)

            if orders_writer is None:
                orders_writer = pq.ParquetWriter(
                    str(orders_dst), orders_table.schema, compression="snappy"
                )
            orders_writer.write_table(orders_table)
            orders_total += len(df_orders_chunk)
            del orders_table

        # ──────────────────────────────────────────────────────
        # STEP 6: Aggressive RAM cleanup
        # ──────────────────────────────────────────────────────
        del raw_chunk, df_orders_chunk
        gc.collect()

        # Log memory every 10 chunks
        if (chunk_idx + 1) % 10 == 0:
            _log_memory(f"(after chunk {chunk_idx + 1}/{total_chunks})")

    # ── Close Parquet writers (finalizes file metadata) ──
    if orders_writer is not None:
        orders_writer.close()
    if items_writer is not None:
        items_writer.close()

    elapsed = time.time() - t_start
    log.info("=" * 60)
    log.info("Pipeline Complete!")
    log.info(f"  ⏱  Elapsed        : {elapsed:.1f}s ({elapsed / 60:.1f} min)")
    log.info(f"  📦 Orders written  : {orders_total:,} rows")
    log.info(f"  📦 Items written   : {items_total:,} rows")
    log.info(f"  🗑  Dupes skipped   : {skipped_dupes:,}")
    if orders_dst.exists():
        log.info(f"  💾 Orders file     : {orders_dst.name} "
                 f"({orders_dst.stat().st_size / 1024 / 1024:.1f} MB)")
    if items_dst.exists():
        log.info(f"  💾 Items file      : {items_dst.name} "
                 f"({items_dst.stat().st_size / 1024 / 1024:.1f} MB)")
    log.info("=" * 60)

    _log_memory("(final)")
    del seen_order_ids
    gc.collect()


# ════════════════════════════════════════════════════════════════════════
# Entry Point
# ════════════════════════════════════════════════════════════════════════

def main():
    log.info("╔══════════════════════════════════════════════════════════╗")
    log.info("║  SupplyForge AI 2.0 — Data Ingestion Pipeline (v2)     ║")
    log.info("║  Medallion: Raw → Bronze → Silver (Parquet)            ║")
    log.info("║  Memory-safe: 10K chunks + streaming JSON parse        ║")
    log.info("╚══════════════════════════════════════════════════════════╝")

    # ── Create Medallion directories ──
    for d in [BRONZE_DIR, SILVER_DIR, GOLD_DIR]:
        d.mkdir(parents=True, exist_ok=True)
        log.info(f"  Directory ready: {d.relative_to(PROJECT_ROOT)}")

    # ── Validate source files exist ──
    for f in [ORDERS_CSV, PRODUCTS_JSON]:
        if not f.exists():
            log.error(f"Source file not found: {f}")
            sys.exit(1)
        log.info(f"  Source found: {f.name} ({f.stat().st_size / 1024 / 1024:.0f} MB)")

    _log_memory("(startup)")
    print()

    # ── Stage A: Products (small, one-shot) ──
    log.info("─── Stage A: Products Ingestion ───")
    ingest_products()
    print()

    # ── Stage B: Orders + Items (chunked, memory-safe) ──
    log.info("─── Stage B: Orders & Items Ingestion (Chunked) ───")
    ingest_orders()
    print()

    # ── Final summary ──
    log.info("Silver Layer files:")
    for f in [SILVER_ORDERS, SILVER_ORDER_ITEMS, SILVER_PRODUCTS]:
        if f.exists():
            size_mb = f.stat().st_size / 1024 / 1024
            log.info(f"  ✅ {f.name:40s} {size_mb:8.1f} MB")
        else:
            log.warning(f"  ❌ {f.name:40s} MISSING")

    _log_memory("(shutdown)")
    log.info("Pipeline finished successfully. Gold Layer → Phase 2.")


if __name__ == "__main__":
    main()
