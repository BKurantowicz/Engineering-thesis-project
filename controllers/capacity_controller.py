"""Physical rack occupancy; reservations never subtract from stored quantities."""

from contextlib import closing
from decimal import Decimal, InvalidOperation
import sqlite3


class CapacityController:
    METRICS = ("weight", "volume")

    def __init__(self, db_path):
        self.db_path = db_path

    @staticmethod
    def positive_decimal(value):
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            return None
        return number if number.is_finite() and number > 0 else None

    @staticmethod
    def is_virtual(location):
        # The reserved braki code is virtual even in legacy/external inserts.
        return bool(location["is_virtual"]) or location["location_code"].strip().casefold() == "braki"

    @staticmethod
    def metric(used, capacity, reasons=()):
        return {
            "used": used,
            "capacity": capacity,
            "percentage": used * 100 / capacity if not reasons and capacity else None,
            "reasons": sorted(set(reasons)),
        }

    def get_capacity(self):
        """Read a single consistent snapshot without modifying stock or limits."""
        try:
            with closing(sqlite3.connect(self.db_path)) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("BEGIN")
                return self.calculate(connection)
        except sqlite3.Error:
            return {"racks": [], **{
                name: self.metric(None, None, ["database_error"]) for name in self.METRICS
            }}

    def calculate(self, connection):
        """Also usable within a caller's inventory write transaction."""
        locations = connection.execute("SELECT * FROM locations ORDER BY location_code, location_id").fetchall()
        physical = {row["location_id"]: row for row in locations if not self.is_virtual(row)}
        known_ids = {row["location_id"] for row in locations}
        stock = {location_id: [] for location_id in physical}
        unclassified = False
        for row in connection.execute(
            "SELECT i.location_id, i.quantity, p.weight, p.length, p.width, p.height "
            "FROM inventory i LEFT JOIN products p ON p.product_id = i.product_id"
        ):
            if row["location_id"] not in known_ids:
                unclassified = True
            elif row["location_id"] in physical:
                stock[row["location_id"]].append(row)

        racks = []
        for location_id, location in physical.items():
            used = {name: Decimal(0) for name in self.METRICS}
            reasons = {name: [] for name in self.METRICS}
            for item in stock[location_id]:
                quantity = item["quantity"]
                if not isinstance(quantity, int) or quantity < 0:
                    for name in self.METRICS:
                        reasons[name].append("invalid_quantity")
                    continue
                if quantity == 0:
                    continue
                weight = self.positive_decimal(item["weight"])
                dimensions = [self.positive_decimal(item[name]) for name in ("length", "width", "height")]
                if weight is None:
                    reasons["weight"].append("invalid_measurements")
                else:
                    used["weight"] += quantity * weight
                if any(dimension is None for dimension in dimensions):
                    reasons["volume"].append("invalid_measurements")
                else:
                    used["volume"] += quantity * dimensions[0] * dimensions[1] * dimensions[2] / 1_000_000
            rack = {"location_id": location_id, "location_code": location["location_code"]}
            for name in self.METRICS:
                capacity = self.positive_decimal(location["max_" + name])
                total = None if reasons[name] else used[name]
                if capacity is None:
                    reasons[name].append("invalid_limits")
                rack[name] = self.metric(total, capacity, reasons[name])
            racks.append(rack)

        result = {"racks": racks}
        for name in self.METRICS:
            reasons = [reason for rack in racks for reason in rack[name]["reasons"]]
            if not racks:
                reasons.append("no_physical_racks")
            if unclassified:
                reasons.append("unclassified_stock")
            used = None if unclassified or any(rack[name]["used"] is None for rack in racks) else sum(
                (rack[name]["used"] for rack in racks), Decimal(0)
            )
            capacity = None if any(rack[name]["capacity"] is None for rack in racks) else sum(
                (rack[name]["capacity"] for rack in racks), Decimal(0)
            )
            result[name] = self.metric(used, capacity, reasons)
        return result
