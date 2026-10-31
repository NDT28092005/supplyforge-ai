#!/usr/bin/env python3
"""Create deterministic Odoo fixtures for the SupplyForge local E2E path.

This utility is only for the Docker environment in docker-compose.odoo-test.yml.
It creates a database, installs Sales and Inventory, seeds a small catalogue and
creates a dedicated connector account. The account is used read-only by
SupplyForge; the setup actions below deliberately use the local administrator.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xmlrpc.client
from datetime import datetime, timedelta


BASE_URL = os.environ.get("ODOO_TEST_URL", "http://127.0.0.1:8069").rstrip("/")
DATABASE = os.environ.get("ODOO_TEST_DATABASE", "odoo_supplyforge_test")
# The official local Odoo image ships with this database-manager password.
# It is safe only because this fixture is bound to 127.0.0.1 and disposable.
MASTER_PASSWORD = os.environ.get("ODOO_TEST_MASTER_PASSWORD", "admin")
ADMIN_LOGIN = os.environ.get("ODOO_TEST_ADMIN_LOGIN", "admin")
ADMIN_PASSWORD = os.environ.get("ODOO_TEST_ADMIN_PASSWORD", "SupplyForge-Admin-Local-2026!")
READER_LOGIN = os.environ.get("ODOO_TEST_READER_LOGIN", "supplyforge.reader@example.test")
READER_PASSWORD = os.environ.get("ODOO_TEST_READER_PASSWORD", "SupplyForge-Reader-Local-2026!")


def message(text: str) -> None:
    print(f"[odoo-test] {text}", flush=True)


def http_post(path: str, values: dict) -> bytes:
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=urllib.parse.urlencode(values).encode("utf-8"),
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def wait_for_server(timeout_seconds: int = 180) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            common_proxy().version()
            return
        except (OSError, xmlrpc.client.Error):
            time.sleep(2)
    raise RuntimeError("Odoo did not become ready in time.")


def common_proxy():
    return xmlrpc.client.ServerProxy(f"{BASE_URL}/xmlrpc/2/common", allow_none=True)


def object_proxy():
    return xmlrpc.client.ServerProxy(f"{BASE_URL}/xmlrpc/2/object", allow_none=True)


def authenticate(login: str, password: str) -> int:
    return int(common_proxy().authenticate(DATABASE, login, password, {}) or 0)


def wait_for_auth(login: str, password: str, timeout_seconds: int = 180) -> int:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            uid = authenticate(login, password)
            if uid:
                return uid
        except (OSError, xmlrpc.client.Error):
            pass
        time.sleep(2)
    raise RuntimeError(f"Unable to authenticate {login} against Odoo database {DATABASE}.")


def execute(uid: int, model: str, method: str, args: list | None = None, kwargs: dict | None = None):
    return object_proxy().execute_kw(
        DATABASE,
        uid,
        ADMIN_PASSWORD,
        model,
        method,
        args or [],
        kwargs or {},
    )


def search(uid: int, model: str, domain: list, *, limit: int = 0) -> list[int]:
    result = execute(uid, model, "search", [domain], {"limit": limit} if limit else {})
    return [int(item) for item in result]


def read_one(uid: int, model: str, record_id: int, fields: list[str]) -> dict:
    records = execute(uid, model, "read", [[record_id]], {"fields": fields})
    return records[0]


def ensure_database() -> None:
    try:
        if authenticate(ADMIN_LOGIN, ADMIN_PASSWORD):
            message(f"Database {DATABASE} already exists.")
            return
    except (OSError, xmlrpc.client.Error):
        pass

    message(f"Creating database {DATABASE}.")
    try:
        http_post(
            "/web/database/create",
            {
                "master_pwd": MASTER_PASSWORD,
                "name": DATABASE,
                "login": ADMIN_LOGIN,
                "password": ADMIN_PASSWORD,
                "lang": "en_US",
                "country_code": "US",
                "phone": "",
                # Odoo's database endpoint treats any non-empty string as
                # true. An empty value intentionally disables sample records.
                "demo": "",
            },
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Could not create Odoo database: HTTP {exc.code}: {detail}") from exc


def ensure_module(uid: int, technical_name: str) -> int:
    ids = search(uid, "ir.module.module", [["name", "=", technical_name]], limit=1)
    if not ids:
        raise RuntimeError(f"Odoo image does not contain module {technical_name}.")
    module = read_one(uid, "ir.module.module", ids[0], ["state"])
    if module["state"] == "installed":
        return uid
    message(f"Installing Odoo module {technical_name}.")
    execute(uid, "ir.module.module", "button_immediate_install", [ids])
    # Module installation reloads Odoo's registry. Re-authenticate before
    # issuing the next request instead of assuming a synchronous restart.
    return wait_for_auth(ADMIN_LOGIN, ADMIN_PASSWORD)


def ensure_modules(uid: int) -> int:
    for technical_name in ("stock", "sale_management"):
        uid = ensure_module(uid, technical_name)
    return uid


def ensure_reader(uid: int, company_id: int) -> None:
    existing = search(uid, "res.users", [["login", "=", READER_LOGIN]], limit=1)
    values = {
        "name": "SupplyForge local read-only connector",
        "login": READER_LOGIN,
        "password": READER_PASSWORD,
        "company_id": company_id,
        "company_ids": [(6, 0, [company_id])],
        "active": True,
    }
    if existing:
        execute(uid, "res.users", "write", [existing, values])
    else:
        execute(uid, "res.users", "create", [values])


def ensure_product(uid: int, default_code: str, name: str, price: float, cost: float) -> int:
    existing = search(uid, "product.product", [["default_code", "=", default_code]], limit=1)
    values = {
        "name": name,
        "default_code": default_code,
        "detailed_type": "product",
        "list_price": price,
        "standard_price": cost,
        "sale_ok": True,
        "purchase_ok": True,
    }
    if existing:
        execute(uid, "product.product", "write", [existing, values])
        return existing[0]
    return int(execute(uid, "product.product", "create", [values]))


def ensure_sale(uid: int, partner_id: int, product_id: int, product: dict, days_ago: int, quantity: float) -> None:
    reference = f"SF-E2E-{product['default_code']}-{days_ago}D"
    order_date = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")
    existing = search(uid, "sale.order", [["client_order_ref", "=", reference]], limit=1)
    if existing:
        order_id = existing[0]
    else:
        order_id = int(execute(uid, "sale.order", "create", [{
            "partner_id": partner_id,
            "client_order_ref": reference,
            "date_order": order_date,
            "order_line": [(0, 0, {
                "product_id": product_id,
                "name": product["name"],
                "product_uom_qty": quantity,
                "price_unit": product["list_price"],
            })],
        }]))
        execute(uid, "sale.order", "action_confirm", [[order_id]])

    # Delivery, rather than order confirmation alone, populates
    # sale.order.line.qty_delivered, which is the operational fact read by
    # SupplyForge when the POS source is not installed.
    pending_pickings = search(uid, "stock.picking", [
        ["sale_id", "=", order_id],
        ["state", "not in", ["done", "cancel"]],
    ])
    for picking_id in pending_pickings:
        execute(uid, "stock.picking", "action_assign", [[picking_id]])
        execute(uid, "stock.picking", "button_validate", [[picking_id]])
    execute(uid, "sale.order", "write", [[order_id], {"date_order": order_date}])


def set_available_inventory(uid: int, product_id: int, location_id: int, quantity: float) -> None:
    """Apply a stock count through Odoo's public Inventory workflow.

    The low-level helper named ``_update_available_quantity`` cannot be used
    over XML-RPC because Odoo correctly blocks private methods remotely.
    """
    quant_ids = search(uid, "stock.quant", [
        ["product_id", "=", product_id],
        ["location_id", "=", location_id],
    ], limit=1)
    if quant_ids:
        quant_id = quant_ids[0]
        execute(uid, "stock.quant", "write", [[quant_id], {"inventory_quantity": quantity}])
    else:
        quant_id = int(execute(uid, "stock.quant", "create", [{
            "product_id": product_id,
            "location_id": location_id,
            "inventory_quantity": quantity,
        }]))
    try:
        execute(uid, "stock.quant", "action_apply_inventory", [[quant_id]])
    except xmlrpc.client.Fault as exc:
        # Odoo 17 applies the transaction but returns None from this public
        # action. Its XML-RPC endpoint then fails while serializing that None.
        # Do not hide genuine inventory failures behind this narrow exception.
        if "cannot marshal None unless allow_none is enabled" not in str(exc):
            raise


def ensure_receipt(uid: int, product_id: int, product: dict, warehouse: dict, company_id: int) -> None:
    """Create one completed supplier receipt for inbound-context E2E coverage."""
    reference = "SF-E2E-RECEIPT-1005"
    if search(uid, "stock.picking", [["origin", "=", reference]], limit=1):
        return
    receipt_types = search(uid, "stock.picking.type", [
        ["code", "=", "incoming"],
        ["company_id", "=", company_id],
    ], limit=1)
    supplier_locations = search(uid, "stock.location", [["usage", "=", "supplier"]], limit=1)
    destination = warehouse.get("lot_stock_id") or []
    uom = product.get("uom_id") or []
    if not receipt_types or not supplier_locations or not destination or not uom:
        raise RuntimeError("Odoo fixture lacks the locations or UoM required for an incoming receipt.")
    picking_id = int(execute(uid, "stock.picking", "create", [{
        "picking_type_id": receipt_types[0],
        "location_id": supplier_locations[0],
        "location_dest_id": int(destination[0]),
        "origin": reference,
    }]))
    execute(uid, "stock.move", "create", [{
        "name": product["name"],
        "product_id": product_id,
        "product_uom_qty": 30,
        "product_uom": int(uom[0]),
        "location_id": supplier_locations[0],
        "location_dest_id": int(destination[0]),
        "picking_id": picking_id,
    }])
    execute(uid, "stock.picking", "action_confirm", [[picking_id]])
    execute(uid, "stock.picking", "action_assign", [[picking_id]])
    execute(uid, "stock.picking", "button_validate", [[picking_id]])


def seed_catalogue_and_sales(uid: int) -> None:
    warehouse_ids = search(uid, "stock.warehouse", [], limit=1)
    if not warehouse_ids:
        raise RuntimeError("Sales and Inventory modules did not create a company and warehouse.")
    warehouse = read_one(uid, "stock.warehouse", warehouse_ids[0], ["lot_stock_id", "company_id"])
    if not warehouse.get("company_id"):
        raise RuntimeError("The selected Odoo warehouse has no company.")
    company_id = int(warehouse["company_id"][0])
    location_id = int(warehouse["lot_stock_id"][0])

    partner_ids = search(uid, "res.partner", [["email", "=", "buyer@example.test"]], limit=1)
    partner_id = partner_ids[0] if partner_ids else int(execute(uid, "res.partner", "create", [{
        "name": "SupplyForge E2E Buyer",
        "email": "buyer@example.test",
    }]))

    fixtures = [
        ("SF-OD-1001", "Cà phê Arabica 500g", 180000, 90000, 200, [(2, 9), (12, 7), (25, 4)]),
        ("SF-OD-1002", "Trà ô long 250g", 120000, 60000, 120, [(4, 5), (18, 4)]),
        ("SF-OD-1003", "Bình giữ nhiệt 600ml", 350000, 180000, 65, [(8, 2)]),
        ("SF-OD-1004", "Bộ ly thủy tinh", 240000, 110000, 35, [(45, 1)]),
        ("SF-OD-1005", "Túi canvas", 95000, 35000, 90, []),
    ]
    for code, name, price, cost, on_hand, sales in fixtures:
        product_id = ensure_product(uid, code, name, price, cost)
        product = read_one(uid, "product.product", product_id, ["default_code", "name", "list_price", "uom_id"])
        # The setup account can write test data. The connector account only
        # calls SupplyForge's allowlisted XML-RPC read methods.
        set_available_inventory(uid, product_id, location_id, on_hand)
        for days_ago, quantity in sales:
            ensure_sale(uid, partner_id, product_id, product, days_ago, quantity)

    receipt_product_id = ensure_product(uid, "SF-OD-1005", "Túi canvas", 95000, 35000)
    receipt_product = read_one(uid, "product.product", receipt_product_id, ["name", "uom_id"])
    ensure_receipt(uid, receipt_product_id, receipt_product, warehouse, company_id)
    ensure_reader(uid, company_id)
    message("Seeded 5 products, current inventory, delivered sales orders and an incoming receipt.")


def reader_contract_check() -> None:
    uid = int(common_proxy().authenticate(DATABASE, READER_LOGIN, READER_PASSWORD, {}) or 0)
    if not uid:
        raise RuntimeError("The connector account cannot authenticate.")
    result = object_proxy().execute_kw(
        DATABASE,
        uid,
        READER_PASSWORD,
        "res.company",
        "search_read",
        [[]],
        {"fields": ["id", "name"], "limit": 5},
    )
    if not result:
        raise RuntimeError("The connector account cannot read any company.")
    message(f"Reader contract check passed for {READER_LOGIN}; {len(result)} company record(s) visible.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the local SupplyForge Odoo fixture.")
    parser.add_argument(
        "--phase",
        choices=("all", "database", "stock", "sales", "modules", "seed", "verify"),
        default="all",
        help="Run one resumable setup phase; normal local usage should keep the default all.",
    )
    phase = parser.parse_args().phase
    wait_for_server()
    ensure_database()
    if phase == "database":
        message("Database phase complete.")
        return 0
    uid = wait_for_auth(ADMIN_LOGIN, ADMIN_PASSWORD)

    if phase == "stock":
        ensure_module(uid, "stock")
        message("Stock module phase complete.")
        return 0
    if phase == "sales":
        ensure_module(uid, "sale_management")
        message("Sales module phase complete.")
        return 0
    if phase == "modules":
        ensure_modules(uid)
        message("Sales and Inventory module phase complete.")
        return 0

    if phase == "all":
        uid = ensure_modules(uid)
    if phase in {"all", "seed"}:
        seed_catalogue_and_sales(uid)
    if phase in {"all", "verify"}:
        reader_contract_check()
    message("Bootstrap complete.")
    print(json.dumps({
        "base_url": BASE_URL,
        "database": DATABASE,
        "username": READER_LOGIN,
        "api_key": READER_PASSWORD,
    }, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[odoo-test] FAILED: {exc}", file=sys.stderr)
        raise
