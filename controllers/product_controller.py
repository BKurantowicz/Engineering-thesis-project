"""Catalogue maintenance and saleable-quantity filtering."""

from contextlib import closing
from decimal import Decimal, InvalidOperation
import math

from controllers.inventory_controller import InventoryController, WarehouseError, connect


class ProductController:
    TEXT_FIELDS = ("sku", "name_pl", "name_en", "desc_pl", "desc_en")
    MEASUREMENTS = ("weight", "length", "width", "height")
    FIELDS = TEXT_FIELDS + ("price",) + MEASUREMENTS

    def __init__(self, db_path):
        self.db_path = db_path
        self.inventory = InventoryController(db_path)

    @staticmethod
    def number(value, field, optional=False):
        if value is None or str(value).strip() == "":
            if optional:
                return Decimal(0)
            raise WarehouseError("required", field=field)
        try:
            number = Decimal(str(value).strip())
        except InvalidOperation:
            raise WarehouseError("invalid_number", field=field) from None
        if not number.is_finite() or number < 0 or not math.isfinite(float(number)):
            raise WarehouseError("invalid_number", field=field)
        return number

    @classmethod
    def validate(cls, data):
        values = {}
        for field in cls.TEXT_FIELDS:
            value = data.get(field) or ""
            if not isinstance(value, str):
                raise WarehouseError("required", field=field)
            values[field] = value.strip()
            if field in cls.TEXT_FIELDS[:3] and not values[field]:
                raise WarehouseError("required", field=field)
        values["price"] = cls.number(data.get("price"), "price")
        if values["price"].as_tuple().exponent < -2:
            raise WarehouseError("price_precision", field="price")
        for field in cls.MEASUREMENTS:
            values[field] = cls.number(data.get(field), field, optional=True)
        return values

    def get_product(self, product_id):
        with closing(connect(self.db_path)) as connection:
            product = connection.execute("SELECT * FROM products WHERE product_id = ?", (product_id,)).fetchone()
        if product is None:
            raise WarehouseError("product_not_found")
        return dict(product)

    def get_sku_conflicts(self):
        groups = {}
        with closing(connect(self.db_path)) as connection:
            for row in connection.execute("SELECT product_id, sku FROM products ORDER BY product_id"):
                groups.setdefault(row["sku"].strip().casefold(), []).append(row["product_id"])
        return [ids for ids in groups.values() if len(ids) > 1]

    def save_product(self, data, product_id=None):
        values = self.validate(data)
        with closing(connect(self.db_path)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = None
            if product_id is not None:
                previous = connection.execute("SELECT * FROM products WHERE product_id = ?", (product_id,)).fetchone()
                if previous is None:
                    raise WarehouseError("product_not_found")
            for row in connection.execute("SELECT product_id, sku FROM products"):
                if row["product_id"] != product_id and row["sku"].strip().casefold() == values["sku"].casefold():
                    raise WarehouseError("duplicate_sku", field="sku")
            parameters = tuple(float(values[field]) if isinstance(values[field], Decimal) else values[field] for field in self.FIELDS)
            if product_id is None:
                placeholders = ", ".join("?" for _ in self.FIELDS)
                cursor = connection.execute(f"INSERT INTO products ({', '.join(self.FIELDS)}) VALUES ({placeholders})", parameters)
                product_id = cursor.lastrowid
            else:
                assignments = ", ".join(field + " = ?" for field in self.FIELDS)
                connection.execute(f"UPDATE products SET {assignments} WHERE product_id = ?", parameters + (product_id,))
                if any(str(previous[field]) != str(float(values[field])) for field in self.MEASUREMENTS):
                    self.inventory.validate_stored_measurements(connection, product_id)
        return product_id

    def get_products(self, search_term="", location_id=None, min_quantity=None, max_quantity=None, min_price=None, max_price=None):
        ranges = {}
        for field, lower, upper in (("quantity", min_quantity, max_quantity), ("price", min_price, max_price)):
            low = None if lower is None or str(lower).strip() == "" else self.number(lower, field)
            high = None if upper is None or str(upper).strip() == "" else self.number(upper, field)
            if field == "quantity" and any(value is not None and value != value.to_integral_value() for value in (low, high)):
                raise WarehouseError("integer_range", field=field)
            if low is not None and high is not None and low > high:
                raise WarehouseError("inverted_range", field=field)
            ranges[field] = (low, high)
        with closing(connect(self.db_path)) as connection:
            connection.execute("BEGIN")
            products = connection.execute("SELECT * FROM products ORDER BY sku COLLATE NOCASE, product_id").fetchall()
            stock = self.inventory.stock_snapshot(connection)
            if location_id is not None:
                location = connection.execute("SELECT * FROM locations WHERE location_id = ?", (location_id,)).fetchone()
                if location is None or self.inventory.capacity.is_virtual(location):
                    raise WarehouseError("physical_location_required")
        query = search_term.strip().casefold()
        result = []
        for row in products:
            product = dict(row)
            if query and not any(query in product[field].casefold() for field in ("sku", "name_pl", "name_en")):
                continue
            entries = [entry for entry in stock if entry["product_id"] == product["product_id"] and (location_id is None or entry["location_id"] == location_id)]
            # A location filter selects catalogue records actually stored at that rack.
            if location_id is not None and not entries:
                continue
            product["available"] = sum(entry["available"] for entry in entries) if product["is_active"] else 0
            product["physical"] = sum(entry["quantity"] for entry in entries)
            product["reserved"] = sum(entry["reserved"] for entry in entries)
            product["locations"] = ", ".join(entry["location_code"] for entry in entries)
            if any((low is not None and value < low) or (high is not None and value > high)
                   for value, (low, high) in ((Decimal(product["available"]), ranges["quantity"]), (Decimal(str(product["price"])), ranges["price"]))):
                continue
            result.append(product)
        return result

    def set_active(self, product_id, active):
        if not isinstance(active, bool):
            raise WarehouseError("invalid_state")
        with closing(connect(self.db_path)) as connection, connection:
            if connection.execute("UPDATE products SET is_active = ? WHERE product_id = ?", (int(active), product_id)).rowcount != 1:
                raise WarehouseError("product_not_found")

    def delete_product(self, product_id):
        with closing(connect(self.db_path)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM products WHERE product_id = ?", (product_id,)).fetchone() is None:
                raise WarehouseError("product_not_found")
            for table in ("order_items", "inventory", "inventory_transactions", "pick_allocations", "shortage_events"):
                if connection.execute(f"SELECT 1 FROM {table} WHERE product_id = ? LIMIT 1", (product_id,)).fetchone():
                    raise WarehouseError("product_referenced")
            connection.execute("DELETE FROM products WHERE product_id = ?", (product_id,))
