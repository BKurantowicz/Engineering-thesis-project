"""Additive catalogue/picking schema; initialization never replaces business data."""


def initialize_warehouse_schema(cursor):
    product_columns = {row[1].lower() for row in cursor.execute("PRAGMA table_info(products)")}
    if "is_active" not in product_columns:
        cursor.execute("ALTER TABLE products ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))")
    order_columns = {row[1].lower() for row in cursor.execute("PRAGMA table_info(orders)")}
    if "cancellation_reason" not in order_columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN cancellation_reason TEXT")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pick_allocations (
            allocation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            pick_list_id INTEGER NOT NULL REFERENCES pick_lists(pick_list_id),
            order_id INTEGER NOT NULL REFERENCES orders(order_id),
            order_item_id INTEGER NOT NULL REFERENCES order_items(item_id),
            product_id INTEGER NOT NULL REFERENCES products(product_id),
            location_id INTEGER NOT NULL REFERENCES locations(location_id),
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            reserved_quantity INTEGER NOT NULL CHECK (reserved_quantity >= 0),
            picked_quantity INTEGER NOT NULL DEFAULT 0 CHECK (picked_quantity >= 0),
            returned_quantity INTEGER NOT NULL DEFAULT 0 CHECK (returned_quantity >= 0),
            cancelled INTEGER NOT NULL DEFAULT 0 CHECK (cancelled IN (0, 1)),
            CHECK (picked_quantity <= quantity AND reserved_quantity <= quantity),
            CHECK (returned_quantity <= picked_quantity)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pick_allocations_stock ON pick_allocations(product_id, location_id)")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS shortage_events (
            operation_id TEXT PRIMARY KEY,
            pick_list_id INTEGER NOT NULL REFERENCES pick_lists(pick_list_id),
            product_id INTEGER NOT NULL REFERENCES products(product_id),
            source_location_id INTEGER NOT NULL REFERENCES locations(location_id),
            missing_quantity INTEGER NOT NULL CHECK (missing_quantity > 0),
            actual_quantity INTEGER NOT NULL CHECK (actual_quantity >= 0),
            result_json TEXT NOT NULL DEFAULT '{}',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    shortage_columns = {row[1].lower() for row in cursor.execute("PRAGMA table_info(shortage_events)")}
    if "result_json" not in shortage_columns:
        cursor.execute("ALTER TABLE shortage_events ADD COLUMN result_json TEXT NOT NULL DEFAULT '{}'")
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS protect_referenced_product BEFORE DELETE ON products
        WHEN EXISTS (SELECT 1 FROM order_items WHERE product_id = OLD.product_id)
          OR EXISTS (SELECT 1 FROM inventory WHERE product_id = OLD.product_id)
          OR EXISTS (SELECT 1 FROM inventory_transactions WHERE product_id = OLD.product_id)
          OR EXISTS (SELECT 1 FROM pick_allocations WHERE product_id = OLD.product_id)
          OR EXISTS (SELECT 1 FROM shortage_events WHERE product_id = OLD.product_id)
        BEGIN SELECT RAISE(ABORT, 'product_referenced'); END
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS reject_new_item_for_inactive_product BEFORE INSERT ON order_items
        WHEN EXISTS (SELECT 1 FROM products WHERE product_id = NEW.product_id AND is_active = 0)
        BEGIN SELECT RAISE(ABORT, 'inactive_product'); END
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS reject_changed_item_for_inactive_product BEFORE UPDATE OF product_id ON order_items
        WHEN NEW.product_id IS NOT OLD.product_id
          AND EXISTS (SELECT 1 FROM products WHERE product_id = NEW.product_id AND is_active = 0)
        BEGIN SELECT RAISE(ABORT, 'inactive_product'); END
    """)
