"""Transactional physical stock writes shared by catalogue and picking workflows."""

from contextlib import closing
from decimal import Decimal
import sqlite3

from controllers.capacity_controller import CapacityController


class WarehouseError(ValueError):
    def __init__(self, code, **details):
        super().__init__(code)
        self.code = code
        self.details = details


def connect(db_path):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


class InventoryController:
    def __init__(self, db_path):
        self.db_path = db_path
        self.capacity = CapacityController(db_path)

    @staticmethod
    def positive_quantity(quantity):
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise WarehouseError("positive_quantity")
        return quantity

    def get_locations(self):
        with closing(connect(self.db_path)) as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM locations ORDER BY location_code, location_id")
                    if not self.capacity.is_virtual(row)]

    def stock_snapshot(self, connection, product_id=None):
        rows = connection.execute("""
            SELECT i.product_id, i.location_id, i.quantity, l.location_code, l.is_virtual,
                   COALESCE(r.reserved, 0) AS reserved
            FROM inventory i JOIN locations l ON l.location_id = i.location_id
            LEFT JOIN (SELECT product_id, location_id, SUM(reserved_quantity) AS reserved
                       FROM pick_allocations GROUP BY product_id, location_id) r
              ON r.product_id = i.product_id AND r.location_id = i.location_id
            WHERE (? IS NULL OR i.product_id = ?) ORDER BY l.location_code, i.product_id
        """, (product_id, product_id)).fetchall()
        result = []
        for row in rows:
            if self.capacity.is_virtual(row):
                continue
            if not isinstance(row["quantity"], int) or row["quantity"] < 0:
                raise WarehouseError("invalid_stock", location=row["location_code"])
            result.append({**dict(row), "available": max(0, row["quantity"] - row["reserved"])})
        return result

    @staticmethod
    def unit_measures(product):
        values = [CapacityController.positive_decimal(product[field]) for field in ("weight", "length", "width", "height")]
        if any(value is None for value in values):
            raise WarehouseError("measurements_required")
        return {"weight": values[0], "volume": values[1] * values[2] * values[3] / 1_000_000}

    def placement_limits(self, connection, product_id, location_id, quantity):
        product = connection.execute("SELECT * FROM products WHERE product_id = ?", (product_id,)).fetchone()
        if product is None:
            raise WarehouseError("product_not_found")
        unit = self.unit_measures(product)
        capacity = self.capacity.calculate(connection)
        racks = capacity["racks"]
        selected = next((rack for rack in racks if rack["location_id"] == location_id), None)
        if selected is None:
            raise WarehouseError("physical_location_required")
        def problems(rack):
            return [name for name in self.capacity.METRICS
                    if rack[name]["percentage"] is None or rack[name]["used"] + quantity * unit[name] > rack[name]["capacity"]]
        failed = problems(selected)
        if failed:
            alternatives = [rack["location_code"] for rack in racks if not problems(rack)]
            unavailable = any(selected[name]["percentage"] is None for name in failed)
            raise WarehouseError("capacity_data" if unavailable else "capacity_exceeded",
                                 location=selected["location_code"], constraints=failed, alternatives=alternatives)
        return selected

    @staticmethod
    def write_change(connection, product_id, location_id, quantity_change, transaction_type):
        connection.execute("""
            INSERT INTO inventory (product_id, location_id, quantity) VALUES (?, ?, ?)
            ON CONFLICT(product_id, location_id) DO UPDATE SET quantity = quantity + excluded.quantity
        """, (product_id, location_id, quantity_change))
        connection.execute("INSERT INTO inventory_transactions (product_id, location_id, quantity_change, transaction_type) VALUES (?, ?, ?, ?)",
                           (product_id, location_id, quantity_change, transaction_type))

    def add_stock(self, product_id, location_id, quantity):
        self.positive_quantity(quantity)
        with closing(connect(self.db_path)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            self.placement_limits(connection, product_id, location_id, quantity)
            self.write_change(connection, product_id, location_id, quantity, "RECEIPT")

    def validate_stored_measurements(self, connection, product_id):
        locations = {row[0] for row in connection.execute("SELECT location_id FROM inventory WHERE product_id = ? AND quantity > 0", (product_id,))}
        for rack in self.capacity.calculate(connection)["racks"]:
            if rack["location_id"] not in locations:
                continue
            for name in self.capacity.METRICS:
                metric = rack[name]
                if metric["percentage"] is None:
                    raise WarehouseError("capacity_data", location=rack["location_code"], constraints=[name], alternatives=[])
                if metric["used"] > metric["capacity"]:
                    raise WarehouseError("capacity_exceeded", location=rack["location_code"], constraints=[name], alternatives=[])
