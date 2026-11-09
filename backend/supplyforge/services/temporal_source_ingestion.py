"""Ingest the approved operational orders export for temporal model serving.

This adapter is intentionally separate from the permissive CSV importer. It
retains only completed/shipped, non-returned, accounting demand events and does
not persist buyer identity, address, phone or raw order JSON.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile

import pandas as pd
from django.db import transaction
from django.utils import timezone

from supplyforge.ml.temporal_benchmark import VALID_STATUSES, is_real_value, parse_items
from supplyforge.models import Order, OrderItem, Product, TemporalDemandSourceImport, Workspace
from supplyforge.services.temporal_feature_service import CONTRACT_PATH


@dataclass(frozen=True)
class TemporalSourceImportSummary:
    retained_orders: int
    retained_items: int
    skipped_orders: int
    skipped_items: int
    created_products: int


class TemporalSourceIngestionService:
    """Persist a privacy-minimized source compatible with the feature contract."""

    REQUIRED_COLUMNS = [
        "_id", "orderId", "status", "time", "returnId", "notCaculateMoney", "warehouse", "data",
    ]

    @staticmethod
    def _stable_id(workspace_id: int, raw_identifier: str, kind: str) -> str:
        return hashlib.sha256(f"{workspace_id}:{kind}:{raw_identifier}".encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _event_time(value):
        event_time = pd.to_datetime(value, errors="coerce")
        if pd.isna(event_time):
            return None
        event_time = event_time.to_pydatetime()
        return timezone.make_aware(event_time) if timezone.is_naive(event_time) else event_time

    @classmethod
    def import_zip(
        cls,
        *,
        source: Path,
        workspace_id: int,
        replace_existing_source: bool = False,
        chunk_size: int = 20_000,
    ) -> TemporalSourceImportSummary:
        source = Path(source)
        workspace = Workspace.objects.select_related("owner").filter(id=workspace_id).first()
        if not workspace or not workspace.owner_id:
            raise ValueError("Workspace must exist and have an owner before importing temporal source events.")
        if not source.is_file():
            raise FileNotFoundError(f"Source ZIP does not exist: {source}")
        user_id = str(workspace.owner_id)
        source_sha256 = cls._file_sha256(source)
        feature_contract_sha256 = cls._file_sha256(CONTRACT_PATH)
        # Invalidate the old attestation before touching events. If a large
        # import is interrupted, runtime data may be partial; keeping a prior
        # source checksum current would let parity/staging make an unsafe
        # claim. A successful run installs a new current lineage below.
        with transaction.atomic():
            TemporalDemandSourceImport.objects.filter(
                workspace=workspace, is_current=True
            ).update(is_current=False)
            if replace_existing_source:
                Order.objects.filter(
                    workspace=workspace,
                    platform="orders_full_temporal",
                ).delete()

        counters: Counter[str] = Counter()
        names_by_sku: dict[str, str] = {}
        prices_by_sku: dict[str, Decimal] = {}
        seen_raw_ids: set[str] = set()
        seen_order_ids: set[str] = set()
        pending: list[tuple[Order, list[OrderItem]]] = []

        def flush() -> None:
            if not pending:
                return
            ids = [order.id for order, _ in pending]
            existing = set(Order.objects.filter(id__in=ids).values_list("id", flat=True))
            fresh = [(order, items) for order, items in pending if order.id not in existing]
            if not fresh:
                pending.clear()
                return
            with transaction.atomic():
                Order.objects.bulk_create([order for order, _ in fresh], batch_size=2_000)
                OrderItem.objects.bulk_create(
                    [item for _, items in fresh for item in items], batch_size=5_000
                )
            counters["retained_orders"] += len(fresh)
            counters["retained_items"] += sum(len(items) for _, items in fresh)
            pending.clear()

        with ZipFile(source) as archive:
            members = [member for member in archive.namelist() if member.lower().endswith(".csv")]
            if len(members) != 1:
                raise ValueError(f"Expected exactly one CSV in source ZIP, found {members}")
            with archive.open(members[0]) as raw_csv:
                reader = pd.read_csv(raw_csv, usecols=cls.REQUIRED_COLUMNS, chunksize=chunk_size, low_memory=False)
                for chunk in reader:
                    for raw in chunk.to_dict(orient="records"):
                        raw_id = str(raw.get("_id") or "").strip()
                        order_id = str(raw.get("orderId") or "").strip()
                        # Match the benchmark adapter: an export may contain
                        # duplicated internal rows or repeated business order
                        # IDs, and neither may contribute demand twice.
                        if not raw_id or raw_id in seen_raw_ids or (order_id and order_id in seen_order_ids):
                            counters["skipped_orders"] += 1
                            continue
                        seen_raw_ids.add(raw_id)
                        if order_id:
                            seen_order_ids.add(order_id)
                        status = str(raw.get("status") or "").upper().strip()
                        if status not in VALID_STATUSES or is_real_value(raw.get("returnId")):
                            counters["skipped_orders"] += 1
                            continue
                        if pd.to_numeric(raw.get("notCaculateMoney"), errors="coerce") == 1:
                            counters["skipped_orders"] += 1
                            continue
                        event_time = cls._event_time(raw.get("time"))
                        items = parse_items(raw.get("data"))
                        if event_time is None or not items:
                            counters["skipped_orders"] += 1
                            continue

                        order = Order(
                            id=cls._stable_id(workspace_id, raw_id, "order"),
                            user_id=user_id,
                            workspace=workspace,
                            order_id=order_id or raw_id,
                            platform="orders_full_temporal",
                            status=status,
                            return_identifier=None,
                            is_accounting=True,
                            warehouse_code=str(raw.get("warehouse") or "").strip() or None,
                            source_event_at=event_time,
                            demand_eligibility_verified=True,
                            created_at=event_time,
                            updated_at=timezone.now(),
                            data=None,
                        )
                        order_items: list[OrderItem] = []
                        for item in items:
                            if not isinstance(item, dict):
                                counters["skipped_items"] += 1
                                continue
                            sku = item.get("model_sku") or item.get("item_sku") or item.get("model_id")
                            quantity = pd.to_numeric(
                                item.get("model_quantity_purchased", item.get("quantity_purchased")), errors="coerce"
                            )
                            if not is_real_value(sku) or pd.isna(quantity) or float(quantity) <= 0:
                                counters["skipped_items"] += 1
                                continue
                            canonical_sku = str(sku).strip()
                            price = pd.to_numeric(
                                item.get("model_discounted_price", item.get("selling_price")), errors="coerce"
                            )
                            unit_price = Decimal(str(float(price))) if not pd.isna(price) and float(price) >= 0 else None
                            product_name = str(item.get("item_name") or item.get("model_name") or canonical_sku)
                            names_by_sku.setdefault(canonical_sku, product_name)
                            if unit_price is not None:
                                prices_by_sku.setdefault(canonical_sku, unit_price)
                            order_items.append(OrderItem(
                                order=order,
                                item_id=str(item.get("item_id") or "") or None,
                                model_id=str(item.get("model_id") or "") or None,
                                sku=canonical_sku,
                                canonical_sku=canonical_sku,
                                product_name=product_name,
                                quantity=int(quantity),
                                price=unit_price,
                                cost=Decimal("0.00"),
                            ))
                        if not order_items:
                            counters["skipped_orders"] += 1
                            continue
                        pending.append((order, order_items))
                        if len(pending) >= 2_000:
                            flush()
        flush()

        existing_skus = set(
            Product.objects.filter(
                workspace=workspace,
                canonical_sku__in=names_by_sku,
            ).values_list("canonical_sku", flat=True)
        )
        products = [
            Product(
                id=cls._stable_id(workspace_id, sku, "product"),
                user_id=user_id,
                workspace=workspace,
                third_party_id=f"orders_full:{sku}",
                item_sku=sku,
                canonical_sku=sku,
                product_name=name,
                platform="orders_full_temporal",
                price=prices_by_sku.get(sku),
                cost=None,
                stock=None,
                active_on_web=True,
            )
            for sku, name in names_by_sku.items() if sku not in existing_skus
        ]
        if products:
            Product.objects.bulk_create(products, batch_size=2_000, ignore_conflicts=True)
        summary = TemporalSourceImportSummary(
            retained_orders=int(counters["retained_orders"]),
            retained_items=int(counters["retained_items"]),
            skipped_orders=int(counters["skipped_orders"]),
            skipped_items=int(counters["skipped_items"]),
            created_products=len(products),
        )
        # Only a completed import can become the source asserted by a future
        # parity report. Historical rows remain for audit, while exactly one
        # current row identifies the source expected by serving validation.
        with transaction.atomic():
            TemporalDemandSourceImport.objects.create(
                workspace=workspace,
                source_sha256=source_sha256,
                source_name=source.name[:255],
                feature_contract_sha256=feature_contract_sha256,
                retained_orders=summary.retained_orders,
                retained_items=summary.retained_items,
                skipped_orders=summary.skipped_orders,
                skipped_items=summary.skipped_items,
                is_current=True,
            )
        return summary
