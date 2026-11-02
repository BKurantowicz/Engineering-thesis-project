"""Additive order-entry schema. NULL distinguishes unknown historical amounts."""
def initialize_sales_schema(cursor):
    columns = {
        "products": {"ean":"TEXT"},
        "orders": {"channel": "TEXT", "external_ref": "TEXT", "sales_snapshot": "TEXT",
                   "net_cents": "INTEGER", "delivery_cents": "INTEGER", "held": "INTEGER NOT NULL DEFAULT 0"},
        "order_shipments": {"dispatched_at": "TEXT", "package_id": "INTEGER REFERENCES packages(package_id)"},
        "invoices": {"document": "TEXT"},
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
    cursor.execute("""CREATE UNIQUE INDEX IF NOT EXISTS dispatch_package ON order_shipments(package_id)
                      WHERE package_id IS NOT NULL""")
    cursor.execute("""CREATE UNIQUE INDEX IF NOT EXISTS dispatch_tracking ON order_shipments(tracking_number)
                      WHERE package_id IS NOT NULL AND tracking_number IS NOT NULL""")
    cursor.execute("""CREATE UNIQUE INDEX IF NOT EXISTS sales_invoice ON invoices(order_id) WHERE document IS NOT NULL""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS parcel_contents (
        package_id INTEGER NOT NULL REFERENCES packages(package_id),
        item_id INTEGER NOT NULL REFERENCES order_items(item_id),
        quantity INTEGER NOT NULL CHECK(quantity>0), PRIMARY KEY(package_id,item_id))""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS dispatch_mail (
        shipment_id INTEGER PRIMARY KEY REFERENCES order_shipments(shipment_id),
        recipient TEXT, message TEXT NOT NULL, invoice_id INTEGER REFERENCES invoices(invoice_id),
        state TEXT NOT NULL DEFAULT 'pending', detail TEXT)""")
