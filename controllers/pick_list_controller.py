"""Persisted picking with explicit source allocations and cumulative confirmation."""

from contextlib import closing

from controllers.inventory_controller import InventoryController, WarehouseError, connect


class PickListController:
    def __init__(self, db_path):
        self.db_path = db_path
        self.inventory = InventoryController(db_path)

    @staticmethod
    def order_fulfilled(connection, order_id):
        items = connection.execute("SELECT item_id, quantity FROM order_items WHERE order_id = ?", (order_id,)).fetchall()
        if any(not isinstance(item["quantity"], int) or item["quantity"] <= 0 for item in items):
            return False
        return bool(items) and all(connection.execute(
            "SELECT COALESCE(SUM(picked_quantity - returned_quantity), 0) FROM pick_allocations WHERE order_item_id = ?",
            (item["item_id"],),
        ).fetchone()[0] >= item["quantity"] for item in items)

    def eligible_orders(self, connection):
        orders = connection.execute("""
            SELECT o.* FROM orders o WHERE o.status_code IN ('NEW', 'IN_PROGRESS')
            AND NOT EXISTS (SELECT 1 FROM pick_list_orders po JOIN pick_lists pl ON pl.pick_list_id = po.pick_list_id
                            WHERE po.order_id = o.order_id AND pl.status != 'CLOSED')
            ORDER BY datetime(o.order_date), o.order_id
        """).fetchall()
        return [dict(order) for order in orders if not self.order_fulfilled(connection, order["order_id"])]

    def get_eligible_orders(self):
        with closing(connect(self.db_path)) as connection:
            return self.eligible_orders(connection)

    def allocation_options(self, order_ids):
        with closing(connect(self.db_path)) as connection:
            connection.execute("BEGIN")
            eligible = {order["order_id"] for order in self.eligible_orders(connection)}
            if not order_ids or not set(order_ids).issubset(eligible):
                raise WarehouseError("order_not_eligible")
            stock = self.inventory.stock_snapshot(connection)
            items = []
            for order_id in order_ids:
                rows = connection.execute("""
                    SELECT oi.*, p.sku, p.name_pl, p.name_en FROM order_items oi
                    JOIN products p ON p.product_id = oi.product_id WHERE oi.order_id = ? ORDER BY oi.item_id
                """, (order_id,)).fetchall()
                if not rows:
                    raise WarehouseError("order_has_no_items")
                for row in rows:
                    items.append({**dict(row), "sources": [entry for entry in stock if entry["product_id"] == row["product_id"]]})
            return items

    def create_list(self, order_ids, allocations):
        if not order_ids or len(set(order_ids)) != len(order_ids):
            raise WarehouseError("select_orders")
        with closing(connect(self.db_path)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            eligible = {order["order_id"] for order in self.eligible_orders(connection)}
            if not set(order_ids).issubset(eligible):
                raise WarehouseError("order_not_eligible")
            items = {}
            for order_id in order_ids:
                order_items = connection.execute("SELECT * FROM order_items WHERE order_id = ?", (order_id,)).fetchall()
                if not order_items:
                    raise WarehouseError("order_has_no_items")
                for item in order_items:
                    self.inventory.positive_quantity(item["quantity"])
                    if connection.execute("SELECT 1 FROM products WHERE product_id = ?", (item["product_id"],)).fetchone() is None:
                        raise WarehouseError("product_not_found")
                    items[item["item_id"]] = item
            stock = {(entry["product_id"], entry["location_id"]): entry["available"] for entry in self.inventory.stock_snapshot(connection)}
            allocated = {item_id: 0 for item_id in items}
            checked = []
            for line in allocations:
                item_id, location_id, quantity = line["order_item_id"], line["location_id"], line["quantity"]
                self.inventory.positive_quantity(quantity)
                if item_id not in items:
                    raise WarehouseError("allocation_mismatch")
                item = items[item_id]
                key = (item["product_id"], location_id)
                if key not in stock or stock[key] < quantity:
                    raise WarehouseError("insufficient_available")
                stock[key] -= quantity
                allocated[item_id] += quantity
                checked.append((item["order_id"], item_id, item["product_id"], location_id, quantity, quantity))
            if any(allocated[item_id] != item["quantity"] for item_id, item in items.items()):
                raise WarehouseError("allocation_mismatch")
            list_id = connection.execute("INSERT INTO pick_lists (status) VALUES ('PENDING')").lastrowid
            connection.executemany("INSERT INTO pick_list_orders (pick_list_id, order_id) VALUES (?, ?)", [(list_id, order_id) for order_id in order_ids])
            connection.executemany("INSERT INTO pick_allocations (pick_list_id, order_id, order_item_id, product_id, location_id, quantity, reserved_quantity) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                   [(list_id,) + line for line in checked])
            return list_id

    def get_lists(self):
        with closing(connect(self.db_path)) as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM pick_lists ORDER BY created_at DESC, pick_list_id DESC")]

    def get_rack_quantity(self, product_id, location_id):
        with closing(connect(self.db_path)) as connection:
            row = connection.execute("SELECT quantity FROM inventory WHERE product_id = ? AND location_id = ?", (product_id, location_id)).fetchone()
            if row is None or not isinstance(row[0], int) or row[0] < 0:
                raise WarehouseError("invalid_actual_quantity")
            return row[0]

    def get_list(self, list_id):
        with closing(connect(self.db_path)) as connection:
            connection.execute("BEGIN")
            row = connection.execute("SELECT * FROM pick_lists WHERE pick_list_id = ?", (list_id,)).fetchone()
            if row is None:
                raise WarehouseError("list_not_found")
            lines = [dict(line) for line in connection.execute("""
                SELECT a.*, p.sku, p.name_pl, p.name_en, l.location_code, o.status_code AS order_status
                FROM pick_allocations a JOIN products p ON p.product_id = a.product_id
                JOIN locations l ON l.location_id = a.location_id JOIN orders o ON o.order_id = a.order_id
                WHERE a.pick_list_id = ? ORDER BY a.order_id, a.order_item_id, a.allocation_id
            """, (list_id,))]
            return {**dict(row), "lines": lines}

    def start_list(self, list_id):
        with closing(connect(self.db_path)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT status FROM pick_lists WHERE pick_list_id = ?", (list_id,)).fetchone()
            if row is None or row[0] not in ("PENDING", "IN_PROGRESS"):
                raise WarehouseError("list_not_open")
            connection.execute("UPDATE pick_lists SET status = 'IN_PROGRESS' WHERE pick_list_id = ?", (list_id,))
            connection.execute("UPDATE orders SET status_code = 'IN_PROGRESS' WHERE status_code = 'NEW' AND order_id IN (SELECT order_id FROM pick_list_orders WHERE pick_list_id = ?)", (list_id,))

    def confirm_pick(self, allocation_id, picked_total):
        if isinstance(picked_total, bool) or not isinstance(picked_total, int) or picked_total < 0:
            raise WarehouseError("invalid_picked_total")
        with closing(connect(self.db_path)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT a.*, pl.status FROM pick_allocations a JOIN pick_lists pl ON pl.pick_list_id = a.pick_list_id WHERE allocation_id = ?", (allocation_id,)).fetchone()
            if row is None:
                raise WarehouseError("allocation_not_found")
            if picked_total == row["picked_quantity"]:
                return
            if row["status"] != "IN_PROGRESS" or row["cancelled"]:
                raise WarehouseError("list_not_started")
            delta = picked_total - row["picked_quantity"]
            if delta <= 0 or delta > row["reserved_quantity"] or picked_total > row["quantity"]:
                raise WarehouseError("invalid_picked_total")
            stock = connection.execute("SELECT quantity FROM inventory WHERE product_id = ? AND location_id = ?", (row["product_id"], row["location_id"])).fetchone()
            if stock is None or stock[0] < delta:
                raise WarehouseError("physical_shortage")
            self.inventory.write_change(connection, row["product_id"], row["location_id"], -delta, "PICK")
            connection.execute("UPDATE pick_allocations SET picked_quantity = ?, reserved_quantity = reserved_quantity - ? WHERE allocation_id = ?", (picked_total, delta, allocation_id))

    def close_list(self, list_id):
        with closing(connect(self.db_path)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT status FROM pick_lists WHERE pick_list_id = ?", (list_id,)).fetchone()
            if row is None:
                raise WarehouseError("list_not_found")
            if row[0] == "CLOSED":
                return
            lines = connection.execute("SELECT * FROM pick_allocations WHERE pick_list_id = ?", (list_id,)).fetchall()
            if not lines or any(line["reserved_quantity"] or (not line["cancelled"] and line["picked_quantity"] != line["quantity"]) for line in lines):
                raise WarehouseError("list_incomplete")
            connection.execute("UPDATE pick_lists SET status = 'CLOSED' WHERE pick_list_id = ?", (list_id,))

    def get_missing_stock(self):
        with closing(connect(self.db_path)) as connection:
            return [dict(row) for row in connection.execute("""
                SELECT s.*, p.sku, l.location_code FROM shortage_events s
                JOIN products p ON p.product_id = s.product_id
                JOIN locations l ON l.location_id = s.source_location_id
                ORDER BY s.created_at DESC, s.operation_id
            """)]
