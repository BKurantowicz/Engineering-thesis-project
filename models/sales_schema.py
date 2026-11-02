"""Additive order-entry schema. NULL distinguishes unknown historical amounts."""
def initialize_sales_schema(cursor):
    columns = {
        "products": {"ean":"TEXT"},
        "orders": {"channel": "TEXT", "external_ref": "TEXT", "sales_snapshot": "TEXT",
                   "net_cents": "INTEGER", "delivery_cents": "INTEGER", "held": "INTEGER NOT NULL DEFAULT 0"},
        "order_shipments": {"dispatched_at": "TEXT"},
        "order_items": {"sale_snapshot": "TEXT"},
    }
    for table, additions in columns.items():
        existing = {r[1] for r in cursor.execute(f"PRAGMA table_info({table})")}
        for name, definition in additions.items():
            if name not in existing:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
    cursor.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_order_channel_ref
                      ON orders(channel COLLATE NOCASE, external_ref COLLATE NOCASE)
                      WHERE external_ref IS NOT NULL AND external_ref != ''""")
