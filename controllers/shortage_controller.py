"""Atomic shortage reconciliation across every open list affected by a count."""

from collections import defaultdict
from contextlib import closing
import json

from controllers.inventory_controller import InventoryController, WarehouseError, connect


class ShortageController:
    def __init__(self, db_path):
        self.db_path = db_path
        self.inventory = InventoryController(db_path)

    def return_stock(self, connection, product_id, preferred_location, quantity, operation_id):
        product = connection.execute("SELECT * FROM products WHERE product_id = ?", (product_id,)).fetchone()
        if product is None:
            raise WarehouseError("product_not_found")
        unit = self.inventory.unit_measures(product)
        racks = self.inventory.capacity.calculate(connection)["racks"]
        racks.sort(key=lambda rack: (rack["location_id"] != preferred_location, rack["location_code"], rack["location_id"]))
        remaining = quantity
        returns = []
        for rack in racks:
            if any(rack[name]["percentage"] is None for name in self.inventory.capacity.METRICS):
                continue
            fits = min(int((rack[name]["capacity"] - rack[name]["used"]) // unit[name]) for name in self.inventory.capacity.METRICS)
            placed = min(remaining, max(0, fits))
            if placed:
                self.inventory.write_change(connection, product_id, rack["location_id"], placed, "RETURN:" + operation_id)
                returns.append({"product_id": product_id, "location_id": rack["location_id"], "quantity": placed})
                remaining -= placed
            if not remaining:
                return returns
        raise WarehouseError("return_capacity")

    def reconcile(self, list_id, product_id, location_id, actual_quantity, operation_id, recorded_quantity=None):
        if isinstance(actual_quantity, bool) or not isinstance(actual_quantity, int) or actual_quantity < 0:
            raise WarehouseError("invalid_actual_quantity")
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise WarehouseError("operation_required")
        with closing(connect(self.db_path)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = connection.execute("SELECT * FROM shortage_events WHERE operation_id = ?", (operation_id,)).fetchone()
            if prior:
                if (prior["pick_list_id"], prior["product_id"], prior["source_location_id"], prior["actual_quantity"]) != (list_id, product_id, location_id, actual_quantity):
                    raise WarehouseError("operation_conflict")
                return json.loads(prior["result_json"])
            pick_list = connection.execute("SELECT status FROM pick_lists WHERE pick_list_id = ?", (list_id,)).fetchone()
            if pick_list is None or pick_list[0] not in ("PENDING", "IN_PROGRESS"):
                raise WarehouseError("list_not_open")
            if connection.execute("SELECT 1 FROM pick_allocations WHERE pick_list_id = ? AND product_id = ? AND location_id = ?", (list_id, product_id, location_id)).fetchone() is None:
                raise WarehouseError("allocation_not_found")
            location = connection.execute("SELECT * FROM locations WHERE location_id = ?", (location_id,)).fetchone()
            if location is None or self.inventory.capacity.is_virtual(location):
                raise WarehouseError("physical_location_required")
            stock = connection.execute("SELECT quantity FROM inventory WHERE product_id = ? AND location_id = ?", (product_id, location_id)).fetchone()
            if stock is not None and recorded_quantity is not None and stock[0] != recorded_quantity:
                raise WarehouseError("stock_changed")
            if stock is None or not isinstance(stock[0], int) or actual_quantity >= stock[0]:
                raise WarehouseError("no_shortage")
            missing = stock[0] - actual_quantity
            affected_lists = {list_id} | {row[0] for row in connection.execute("""
                SELECT DISTINCT a.pick_list_id FROM pick_allocations a
                JOIN pick_lists p ON p.pick_list_id = a.pick_list_id
                WHERE a.product_id = ? AND a.location_id = ? AND a.reserved_quantity > 0
                  AND p.status IN ('PENDING', 'IN_PROGRESS')
            """, (product_id, location_id))}
            marks = ",".join("?" for _ in affected_lists)
            orders = connection.execute(f"""
                SELECT DISTINCT o.* FROM orders o JOIN pick_list_orders po ON po.order_id = o.order_id
                WHERE po.pick_list_id IN ({marks}) AND o.status_code IN ('NEW', 'IN_PROGRESS')
                ORDER BY datetime(o.order_date), o.order_id
            """, tuple(sorted(affected_lists))).fetchall()
            order_ids = [order["order_id"] for order in orders]
            order_marks = ",".join("?" for _ in order_ids)
            allocations = [dict(row) for row in connection.execute(
                f"SELECT * FROM pick_allocations WHERE order_id IN ({order_marks}) ORDER BY allocation_id", order_ids,
            )] if order_ids else []
            items = [dict(row) for row in connection.execute(
                f"SELECT * FROM order_items WHERE order_id IN ({order_marks}) ORDER BY item_id", order_ids,
            )] if order_ids else []
            demand = defaultdict(lambda: defaultdict(int))
            for item in items:
                self.inventory.positive_quantity(item["quantity"])
                demand[item["order_id"]][item["product_id"]] += item["quantity"]

            # The count changes physical stock once; affected reservations are then
            # released together so the oldest complete orders can be selected.
            self.inventory.write_change(connection, product_id, location_id, -missing, "SHORTAGE:" + operation_id)
            if order_ids:
                connection.execute(f"UPDATE pick_allocations SET reserved_quantity = 0 WHERE order_id IN ({order_marks})", order_ids)
            pool = defaultdict(int)
            for entry in self.inventory.stock_snapshot(connection):
                pool[entry["product_id"]] += entry["available"]
            picked = defaultdict(int)
            for line in allocations:
                held = line["picked_quantity"] - line["returned_quantity"]
                pool[line["product_id"]] += held
                picked[line["order_item_id"]] += held
            if any(picked[item["item_id"]] > item["quantity"] for item in items):
                raise WarehouseError("invalid_picking_history")
            fulfilled, cancelled = [], []
            for order_id in order_ids:
                if demand[order_id] and all(pool[product] >= quantity for product, quantity in demand[order_id].items()):
                    fulfilled.append(order_id)
                    for product, quantity in demand[order_id].items():
                        pool[product] -= quantity
                else:
                    cancelled.append(order_id)

            returns = []
            for line in allocations:
                if line["order_id"] in cancelled:
                    quantity = line["picked_quantity"] - line["returned_quantity"]
                    if quantity:
                        returns.extend(self.return_stock(connection, line["product_id"], line["location_id"], quantity, operation_id))
                        connection.execute("UPDATE pick_allocations SET returned_quantity = picked_quantity WHERE allocation_id = ?", (line["allocation_id"],))
                # Preserve old allocations/progress as resolved history. Replacement
                # reservations below describe the explicit reconciliation result.
                connection.execute("UPDATE pick_allocations SET cancelled = 1 WHERE allocation_id = ?", (line["allocation_id"],))
            connection.execute("INSERT OR IGNORE INTO dict_order_statuses (status_code, name_pl, name_en) VALUES ('CANCELLED', 'Anulowane', 'Cancelled')")
            for order_id in cancelled:
                connection.execute("UPDATE orders SET status_code = 'CANCELLED', cancellation_reason = ? WHERE order_id = ?", ("SHORTAGE:" + operation_id, order_id))

            available = {(entry["product_id"], entry["location_id"]): entry for entry in self.inventory.stock_snapshot(connection)}
            for item in items:
                if item["order_id"] not in fulfilled:
                    continue
                remaining = item["quantity"] - picked[item["item_id"]]
                original = [line for line in allocations if line["order_item_id"] == item["item_id"]]
                list_for_order = next((line["pick_list_id"] for line in original), None)
                if list_for_order is None:
                    raise WarehouseError("invalid_picking_history")
                preferred = {line["location_id"] for line in original}
                sources = sorted((entry for key, entry in available.items() if key[0] == item["product_id"]),
                                 key=lambda entry: (entry["location_id"] not in preferred, entry["location_code"], entry["location_id"]))
                for source in sources:
                    take = min(remaining, source["available"])
                    if take:
                        connection.execute("INSERT INTO pick_allocations (pick_list_id, order_id, order_item_id, product_id, location_id, quantity, reserved_quantity) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                           (list_for_order, item["order_id"], item["item_id"], item["product_id"], source["location_id"], take, take))
                        source["available"] -= take
                        remaining -= take
                    if not remaining:
                        break
                if remaining:
                    raise WarehouseError("insufficient_available")

            virtual = next((row for row in connection.execute("SELECT * FROM locations ORDER BY location_id")
                            if row["location_code"].strip().casefold() == "braki"), None)
            if virtual is None:
                virtual_id = connection.execute("INSERT INTO locations (location_code, max_weight, max_volume, is_virtual) VALUES ('braki', 0, 0, 1)").lastrowid
            else:
                virtual_id = virtual["location_id"]
                connection.execute("UPDATE locations SET is_virtual = 1 WHERE location_id = ?", (virtual_id,))
            self.inventory.write_change(connection, product_id, virtual_id, missing, "MISSING:" + operation_id)
            result = {"fulfilled": fulfilled, "cancelled": cancelled, "affected_lists": sorted(affected_lists),
                      "missing_quantity": missing, "returns": returns, "previous_allocations": allocations}
            connection.execute("INSERT INTO shortage_events (operation_id, pick_list_id, product_id, source_location_id, missing_quantity, actual_quantity, result_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                               (operation_id, list_id, product_id, location_id, missing, actual_quantity, json.dumps(result)))
            return result
