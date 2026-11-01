"""Explicitly create or replace a designated mock database with coherent workflows."""

import argparse
from contextlib import closing
from datetime import datetime, timedelta
import gc
import os
from pathlib import Path
import sqlite3
import tempfile

from controllers.customer_controller import CustomerController
from controllers.order_controller import OrderController
from controllers.pick_list_controller import PickListController
from controllers.product_controller import ProductController
from controllers.shortage_controller import ShortageController
from models.database import DatabaseManager


def build_demo(db_path):
    DatabaseManager(str(db_path))
    customers = CustomerController(str(db_path))
    products = ProductController(str(db_path))
    orders = OrderController(str(db_path))
    picking = PickListController(str(db_path))
    with closing(sqlite3.connect(db_path)) as connection, connection:
        connection.executemany("INSERT INTO locations (location_id, location_code, max_weight, max_volume) VALUES (?, ?, ?, ?)",
                               [(1, "A-01", 500, 1), (2, "B-01", 750, 1.5), (3, "C-01", 500, 1)])
    customer_ids = [customers.save_customer(dict(first_name=first, last_name=last, email=email, phone=phone,
                                                street=street, postal_code=postal, city=city))
                    for first, last, email, phone, street, postal, city in (
                        ("Anna", "Nowak", "anna@example.test", "+48 500 100 101", "Sample Street 1", "00-001", "Warsaw"),
                        ("Alex", "Smith", "alex@example.test", "", "Example Road 2", "SW1A 1AA", "London"),
                        ("Maria", "Kowalska", "maria@example.test", "+48 500 100 103", "Demo Street 3", "80-001", "Gdansk"),
                    )]
    definitions = (
        ("DEMO-LAPTOP", "Laptop", "Laptop", "2499.00", "2.2", "35", "25", "5"),
        ("DEMO-KEYBOARD", "Klawiatura", "Keyboard", "149.00", "0.8", "45", "15", "4"),
        ("DEMO-MONITOR", "Monitor", "Monitor", "899.00", "5.5", "55", "40", "12"),
        ("DEMO-CABLE", "Kabel", "Cable", "29.00", "0.2", "20", "10", "3"),
        ("DEMO-DOCK", "Stacja dokująca", "Dock", "249.00", "0.4", "15", "10", "4"),
    )
    product_ids = [products.save_product(dict(zip(("sku", "name_pl", "name_en", "price", "weight", "length", "width", "height"), definition))) for definition in definitions]
    laptop, keyboard, monitor, cable, dock = product_ids
    for product_id, location_id, quantity in ((laptop, 1, 20), (laptop, 2, 10), (keyboard, 1, 25), (monitor, 2, 20), (cable, 1, 40), (dock, 3, 1)):
        products.inventory.add_stock(product_id, location_id, quantity)
    def make_list(customer_id, demands, days_ago):
        total = sum(products.get_product(product_id)["price"] * quantity for product_id, quantity, _ in demands)
        customer = customers.get_customer(customer_id)
        order_id = orders.add_order(customer_id, 1, None, total, {"name": customer["first_name"], "second_name": customer["last_name"], "street": customer["street"], "postal_code": customer["postal_code"], "city": customer["city"]})
        allocations = []
        with closing(sqlite3.connect(db_path)) as connection, connection:
            connection.execute("UPDATE orders SET order_date = ? WHERE order_id = ?", ((datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S"), order_id))
            for product_id, quantity, location_id in demands:
                item_id = connection.execute("INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (?, ?, ?, ?)",
                                             (order_id, product_id, quantity, products.get_product(product_id)["price"])).lastrowid
                allocations.append(dict(order_item_id=item_id, location_id=location_id, quantity=quantity))
        return picking.create_list([order_id], allocations)
    open_id = make_list(customer_ids[0], [(laptop, 2, 1), (keyboard, 1, 1)], 3)
    partial_id = make_list(customer_ids[1], [(monitor, 2, 2), (cable, 3, 1)], 2)
    picking.start_list(partial_id)
    monitor_line = next(line for line in picking.get_list(partial_id)["lines"] if line["product_id"] == monitor)
    picking.confirm_pick(monitor_line["allocation_id"], 1)
    closed_id = make_list(customer_ids[2], [(laptop, 1, 1), (keyboard, 1, 1)], 1)
    picking.start_list(closed_id)
    for line in picking.get_list(closed_id)["lines"]:
        picking.confirm_pick(line["allocation_id"], line["quantity"])
    picking.close_list(closed_id)
    shortage_id = make_list(customer_ids[0], [(cable, 3, 1), (dock, 1, 3)], 0)
    picking.start_list(shortage_id)
    cable_line = next(line for line in picking.get_list(shortage_id)["lines"] if line["product_id"] == cable)
    picking.confirm_pick(cable_line["allocation_id"], 3)
    ShortageController(str(db_path)).reconcile(shortage_id, dock, 3, 0, "DEMO-SHORTAGE-1")
    picking.close_list(shortage_id)
    customers.set_active(customer_ids[2], False)
    return {"open": open_id, "partial": partial_id, "closed": closed_id, "shortage": shortage_id}


def seed_demo(db_path, replace_mock=False):
    target = Path(db_path).expanduser().resolve()
    if target.exists() and not replace_mock:
        raise FileExistsError("The database exists. Use --replace-mock only for a designated mock database.")
    if any(Path(str(target) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise RuntimeError("Close the application and its database connections before replacing mock data.")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, filename = tempfile.mkstemp(prefix=".thesis-demo-", suffix=".db", dir=target.parent)
    os.close(descriptor)
    temporary = Path(filename)
    try:
        result = build_demo(temporary)
        gc.collect()
        os.replace(temporary, target)
        return result
    finally:
        gc.collect()
        if temporary.exists():
            temporary.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, help="Explicit path to the development/demo database.")
    parser.add_argument("--replace-mock", action="store_true", help="Replace the designated existing mock database after the complete dataset validates.")
    args = parser.parse_args()
    try:
        result = seed_demo(args.database, args.replace_mock)
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
        parser.exit(1, str(error) + "\n")
    print("Created coherent demonstration lists:", result)


if __name__ == "__main__":
    main()
