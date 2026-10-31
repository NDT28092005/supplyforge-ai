"""Load the SupplyForge 1,000-SKU E2E CSV into a clean Odoo database.

This script is executed *inside* ``odoo shell`` by the ``odoo-csv-seed``
Compose service. It deliberately uses the Odoo ORM instead of XML-RPC so a
21,750-line fixture is seeded in bounded, transactional batches.

The resulting source has the same external SKU, day-level sales quantity,
unit price, cost and ending available inventory as the CSV. Sales are grouped
into daily Sales Orders because SupplyForge only consumes the completed line
facts; it does not use the original order IDs.
"""

from __future__ import annotations

import csv
import hashlib
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path


CSV_PATH = Path("/opt/supplyforge-test-data/e2e_balanced_risk_1000_skus.csv")
MARKER_KEY = "supplyforge.e2e.csv.seed.checksum"
READER_LOGIN = "supplyforge.reader@example.test"
READER_PASSWORD = "SupplyForge-Reader-Local-2026!"
CUSTOMER_EMAIL = "supplyforge-e2e-buyer@example.test"
SUPPLIER_EMAIL = "supplyforge-e2e-supplier@example.test"


def log(message: str) -> None:
    print(f"[odoo-csv-e2e] {message}", flush=True)


def decimal(value: str) -> Decimal:
    return Decimal(value).quantize(Decimal("0.0001"))


def load_source():
    if not CSV_PATH.is_file():
        raise RuntimeError(f"CSV fixture is unavailable at {CSV_PATH}.")
    digest = hashlib.sha256(CSV_PATH.read_bytes()).hexdigest()
    by_sku: dict[str, dict] = {}
    by_day: dict[str, list[dict]] = defaultdict(list)

    with CSV_PATH.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        expected = {"item_sku", "product_name", "quantity", "price", "cost", "stock", "order_date"}
        if not reader.fieldnames or not expected.issubset(reader.fieldnames):
            raise RuntimeError("CSV E2E không có đủ cột nguồn cần thiết.")
        for row in reader:
            sku = row["item_sku"].strip()
            order_date = row["order_date"].strip()
            quantity = decimal(row["quantity"])
            stock = decimal(row["stock"])
            data = by_sku.setdefault(sku, {
                "sku": sku,
                "name": row["product_name"].strip(),
                "price": decimal(row["price"]),
                "cost": decimal(row["cost"]),
                "ending_stock": stock,
                "sold_quantity": Decimal("0"),
            })
            if data["ending_stock"] != stock:
                raise RuntimeError(f"SKU {sku} có tồn cuối không nhất quán trong CSV.")
            data["sold_quantity"] += quantity
            by_day[order_date].append({
                "sku": sku,
                "quantity": quantity,
                "price": decimal(row["price"]),
            })
    if len(by_sku) != 1000 or not by_day:
        raise RuntimeError(f"CSV E2E không đúng quy mô mong đợi: {len(by_sku)} SKU.")
    return digest, by_sku, by_day


def first(model, domain):
    return model.search(domain, limit=1)


def ensure_reader(company):
    users = env["res.users"].sudo()  # noqa: F821 - provided by odoo shell
    reader = users.search([("login", "=", READER_LOGIN)], limit=1)
    values = {
        "name": "SupplyForge E2E read-only connector",
        "login": READER_LOGIN,
        "password": READER_PASSWORD,
        "company_id": company.id,
        "company_ids": [(6, 0, [company.id])],
        "active": True,
    }
    if reader:
        reader.write(values)
    else:
        users.create(values)


def ensure_partner(email: str, name: str):
    partner_model = env["res.partner"]  # noqa: F821 - provided by odoo shell
    partner = partner_model.search([("email", "=", email)], limit=1)
    return partner or partner_model.create({"name": name, "email": email})


def create_initial_receipt(products, initial_quantity, warehouse, supplier):
    picking_type = first(env["stock.picking.type"], [  # noqa: F821
        ("code", "=", "incoming"),
        ("warehouse_id", "=", warehouse.id),
    ])
    supplier_location = first(env["stock.location"], [("usage", "=", "supplier")])  # noqa: F821
    if not picking_type or not supplier_location:
        raise RuntimeError("Không tìm thấy loại phiếu nhập hoặc vị trí nhà cung cấp trong Odoo.")
    reference = "SUPPLYFORGE-CSV-E2E-OPENING-RECEIPT"
    existing = env["stock.picking"].search([("origin", "=", reference)], limit=1)  # noqa: F821
    if existing:
        return existing
    moves = []
    for sku, product in products.items():
        moves.append((0, 0, {
            "name": product.display_name,
            "product_id": product.id,
            "product_uom_qty": float(initial_quantity[sku]),
            "product_uom": product.uom_id.id,
            "location_id": supplier_location.id,
            "location_dest_id": warehouse.lot_stock_id.id,
        }))
    picking = env["stock.picking"].create({  # noqa: F821
        "picking_type_id": picking_type.id,
        "partner_id": supplier.id,
        "location_id": supplier_location.id,
        "location_dest_id": warehouse.lot_stock_id.id,
        "origin": reference,
        "scheduled_date": "2026-05-04 08:00:00",
        "move_ids_without_package": moves,
    })
    picking.action_confirm()
    picking.action_assign()
    picking.button_validate()
    picking.move_ids.write({"date": "2026-05-04 08:00:00"})
    return picking


def create_daily_sales(by_day, products, customer):
    order_model = env["sale.order"]  # noqa: F821 - provided by odoo shell
    total_days = len(by_day)
    for index, (day, rows) in enumerate(sorted(by_day.items()), start=1):
        reference = f"SUPPLYFORGE-CSV-E2E-{day}"
        order = order_model.search([("client_order_ref", "=", reference)], limit=1)
        if not order:
            lines = []
            for row in rows:
                product = products[row["sku"]]
                lines.append((0, 0, {
                    "product_id": product.id,
                    "name": product.display_name,
                    "product_uom_qty": float(row["quantity"]),
                    "price_unit": float(row["price"]),
                }))
            order = order_model.create({
                "partner_id": customer.id,
                "client_order_ref": reference,
                "date_order": f"{day} 12:00:00",
                "order_line": lines,
            })
            order.action_confirm()

        pending_pickings = order.picking_ids.filtered(lambda item: item.state not in {"done", "cancel"})
        for picking in pending_pickings:
            picking.action_assign()
            picking.button_validate()
            picking.move_ids.write({"date": f"{day} 12:00:00"})
        # Confirmation writes the current time by default. Restore the source
        # transaction day after delivery so the 90-day risk signals are exact.
        order.write({"date_order": f"{day} 12:00:00"})
        if index % 10 == 0 or index == total_days:
            env.cr.commit()  # noqa: F821 - durable checkpoints for a 21k-line fixture
            log(f"Delivered {index}/{total_days} daily sales orders.")


def verify_ending_inventory(products, expected, warehouse):
    quant_model = env["stock.quant"]  # noqa: F821 - provided by odoo shell
    mismatches = []
    for sku, product in products.items():
        quants = quant_model.search([
            ("product_id", "=", product.id),
            ("location_id", "child_of", warehouse.lot_stock_id.id),
        ])
        observed = sum(quants.mapped("quantity")) - sum(quants.mapped("reserved_quantity"))
        if abs(observed - float(expected[sku])) > 0.0001:
            mismatches.append((sku, observed, float(expected[sku])))
    if mismatches:
        sample = ", ".join(f"{sku}: {actual}/{wanted}" for sku, actual, wanted in mismatches[:5])
        raise RuntimeError(f"Tồn cuối Odoo không khớp CSV ({len(mismatches)} SKU): {sample}")


def main():
    digest, by_sku, by_day = load_source()
    params = env["ir.config_parameter"].sudo()  # noqa: F821 - provided by odoo shell
    if params.get_param(MARKER_KEY) == digest:
        log("CSV fixture has already been seeded; nothing to do.")
        return
    if env["product.product"].search_count([("default_code", "like", "E2E-%")]):  # noqa: F821
        raise RuntimeError("Phát hiện dữ liệu E2E dở dang. Hãy tạo database fixture mới thay vì nạp chồng.")

    company = env.company  # noqa: F821 - provided by odoo shell
    warehouse = first(env["stock.warehouse"], [("company_id", "=", company.id)])  # noqa: F821
    if not warehouse:
        raise RuntimeError("Database Odoo không có kho mặc định.")
    customer = ensure_partner(CUSTOMER_EMAIL, "SupplyForge E2E Sales Customer")
    supplier = ensure_partner(SUPPLIER_EMAIL, "SupplyForge E2E Supplier")

    values = [{
        "name": data["name"],
        "default_code": sku,
        "detailed_type": "product",
        "list_price": float(data["price"]),
        "standard_price": float(data["cost"]),
        "sale_ok": True,
        "purchase_ok": True,
    } for sku, data in sorted(by_sku.items())]
    created = env["product.product"].create(values)  # noqa: F821 - provided by odoo shell
    products = {product.default_code: product for product in created}
    if len(products) != len(by_sku):
        raise RuntimeError("Odoo không tạo đủ 1.000 SKU fixture.")
    log("Created 1,000 products.")

    initial_quantity = {
        sku: data["ending_stock"] + data["sold_quantity"]
        for sku, data in by_sku.items()
    }
    create_initial_receipt(products, initial_quantity, warehouse, supplier)
    env.cr.commit()  # noqa: F821 - receipt supplies all stock before deliveries
    log("Completed opening supplier receipt.")

    create_daily_sales(by_day, products, customer)
    verify_ending_inventory(products, {sku: data["ending_stock"] for sku, data in by_sku.items()}, warehouse)
    ensure_reader(company)
    params.set_param(MARKER_KEY, digest)
    env.cr.commit()  # noqa: F821 - mark only after all business invariants pass
    log(f"Completed: 1,000 SKUs, {sum(len(rows) for rows in by_day.values()):,} sales lines, {len(by_day)} sale orders.")


main()
