"""Transactional expansion of a single warehouse into one relational installation.

This migration is deliberately explicit: callers run it on a backed-up database,
outside a transaction. It never imports a second business database or seeds stock.
"""
import re
import sqlite3


VERSION = 1


def _add(db, table, column, definition):
    if column not in {r[1] for r in db.execute(f'PRAGMA table_info({table})')}:
        db.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')


def _replace_unique(db, table, column):
    """Rebuild only the legacy inline UNIQUE, preserving all columns and triggers."""
    sql = db.execute('SELECT sql FROM sqlite_master WHERE type=\'table\' AND name=?', (table,)).fetchone()[0]
    revised, count = re.subn(rf'(\b{column}\s+TEXT)\s+UNIQUE\b', r'\1', sql, flags=re.I)
    if not count:
        return
    objects = [r[0] for r in db.execute(
        "SELECT sql FROM sqlite_master WHERE tbl_name=? AND type IN ('index','trigger') AND sql IS NOT NULL", (table,))]
    temporary = '_migration_' + table
    revised = re.sub(r'^(CREATE\s+TABLE\s+)(?:IF\s+NOT\s+EXISTS\s+)?[\w"`\[\]]+',
                     lambda m: m[1] + temporary, revised, count=1, flags=re.I)
    columns = ','.join('"' + r[1] + '"' for r in db.execute(f'PRAGMA table_info({table})'))
    sequence = db.execute('SELECT seq FROM sqlite_sequence WHERE name=?', (table,)).fetchone()
    db.execute(revised)
    db.execute(f'INSERT INTO {temporary}({columns}) SELECT {columns} FROM {table}')
    legacy = db.execute('PRAGMA legacy_alter_table').fetchone()[0]
    db.execute('PRAGMA legacy_alter_table=ON')
    try:
        db.execute(f'DROP TABLE {table}')
        db.execute(f'ALTER TABLE {temporary} RENAME TO {table}')
    finally:
        db.execute(f'PRAGMA legacy_alter_table={legacy}')
    if sequence:
        db.execute('UPDATE sqlite_sequence SET seq=? WHERE name=?', (sequence[0], table))
    for sql in objects:
        db.execute(sql)


def initialize_shop_schema(db):
    if db.in_transaction:
        raise ValueError('shop_migration_requires_idle_connection')
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='application_schema'").fetchone():
        version = [r[0] for r in db.execute('SELECT version FROM application_schema')]
        if version != [VERSION]:
            raise ValueError('unsupported_application_schema')
        return
    foreign_keys = db.execute('PRAGMA foreign_keys').fetchone()[0]
    db.execute('PRAGMA foreign_keys=OFF')
    try:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('source_foreign_key_conflict')
        db.execute('CREATE TABLE shops(shop_id INTEGER PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE)')
        db.execute("INSERT INTO shops VALUES(1,'Initial shop','initial shop')")
        db.execute('''CREATE TABLE physical_warehouses(
            warehouse_id INTEGER PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE)''')
        db.execute("INSERT INTO physical_warehouses VALUES(1,'Initial warehouse','initial warehouse')")
        db.execute('''CREATE TABLE shop_warehouses(
            shop_id INTEGER NOT NULL REFERENCES shops, warehouse_id INTEGER NOT NULL REFERENCES physical_warehouses,
            PRIMARY KEY(shop_id,warehouse_id))''')
        db.execute('INSERT INTO shop_warehouses VALUES(1,1)')
        db.execute('''CREATE TABLE shop_prices(
            shop_id INTEGER NOT NULL REFERENCES shops, product_id INTEGER NOT NULL REFERENCES products,
            price_cents INTEGER NOT NULL CHECK(typeof(price_cents)='integer' AND price_cents>=0),
            PRIMARY KEY(shop_id,product_id))''')
        db.execute('''CREATE TABLE shop_settings(
            shop_id INTEGER PRIMARY KEY REFERENCES shops, configuration TEXT NOT NULL DEFAULT '{}')''')
        db.execute('INSERT INTO shop_settings(shop_id) VALUES(1)')
        db.execute('''CREATE TABLE invoice_sequences(
            shop_id INTEGER NOT NULL REFERENCES shops, year INTEGER NOT NULL,
            next_number INTEGER NOT NULL CHECK(next_number>0), PRIMARY KEY(shop_id,year))''')
        db.execute('''CREATE TABLE IF NOT EXISTS accounts(
            user_id TEXT PRIMARY KEY, login TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','employee')),
            must_change INTEGER NOT NULL DEFAULT 1, version INTEGER NOT NULL DEFAULT 1)''')
        _add(db, 'accounts', 'all_shops', 'INTEGER NOT NULL DEFAULT 0 CHECK(all_shops IN (0,1))')
        db.execute('''CREATE TABLE account_shops(
            user_id TEXT NOT NULL REFERENCES accounts, shop_id INTEGER NOT NULL REFERENCES shops,
            PRIMARY KEY(user_id,shop_id))''')
        db.execute('INSERT INTO account_shops SELECT user_id,1 FROM accounts')
        db.execute('''CREATE TABLE IF NOT EXISTS app_state(key TEXT PRIMARY KEY,value TEXT NOT NULL)''')
        for table in ('customers', 'orders', 'pick_lists', 'invoices'):
            _add(db, table, 'shop_id', 'INTEGER NOT NULL DEFAULT 1 REFERENCES shops(shop_id)')
            db.execute(f'CREATE INDEX idx_{table}_shop ON {table}(shop_id)')
        for table in ('locations', 'packages'):
            _add(db, table, 'warehouse_id', 'INTEGER NOT NULL DEFAULT 1 REFERENCES physical_warehouses(warehouse_id)')
        _add(db, 'operation_history', 'shop_id', 'INTEGER REFERENCES shops(shop_id)')
        _add(db, 'operation_history', 'order_id', 'INTEGER REFERENCES orders(order_id)')
        db.execute('UPDATE operation_history SET shop_id=1')
        db.execute('''CREATE TABLE scoped_delivery_receipts(
            delivery_number TEXT NOT NULL, operation_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            warehouse_id INTEGER NOT NULL DEFAULT 1 REFERENCES physical_warehouses,
            PRIMARY KEY(warehouse_id,delivery_number))''')
        db.execute('INSERT INTO scoped_delivery_receipts(delivery_number,operation_id,created_at) SELECT * FROM delivery_receipts')
        db.execute('DROP TABLE delivery_receipts')
        db.execute('ALTER TABLE scoped_delivery_receipts RENAME TO delivery_receipts')
        _replace_unique(db, 'customers', 'email')
        _replace_unique(db, 'locations', 'location_code')
        _replace_unique(db, 'invoices', 'invoice_number')
        db.execute('CREATE UNIQUE INDEX customer_shop_email ON customers(shop_id,email)')
        db.execute('CREATE UNIQUE INDEX warehouse_rack_code ON locations(warehouse_id,location_code)')
        db.execute('CREATE UNIQUE INDEX shop_invoice_number ON invoices(shop_id,invoice_number)')
        db.execute('DROP INDEX IF EXISTS idx_order_channel_ref')
        db.execute('''CREATE UNIQUE INDEX idx_order_channel_ref ON orders(
            shop_id,channel COLLATE NOCASE,external_ref COLLATE NOCASE)
            WHERE external_ref IS NOT NULL AND external_ref != '' ''')
        _relationship_guards(db)
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('migration_foreign_key_conflict')
        db.execute('CREATE TABLE application_schema(version INTEGER NOT NULL)')
        db.execute('INSERT INTO application_schema VALUES(?)', (VERSION,))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.execute(f'PRAGMA foreign_keys={foreign_keys}')


def _relationship_guards(db):
    conditions = {
        'orders': "NEW.customer_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM customers c WHERE c.customer_id=NEW.customer_id AND c.shop_id=NEW.shop_id)",
        'invoices': "NOT EXISTS (SELECT 1 FROM orders o WHERE o.order_id=NEW.order_id AND o.shop_id=NEW.shop_id)",
        'pick_list_orders': "NOT EXISTS (SELECT 1 FROM pick_lists p JOIN orders o ON o.shop_id=p.shop_id WHERE p.pick_list_id=NEW.pick_list_id AND o.order_id=NEW.order_id)",
        'pick_allocations': """NOT EXISTS (SELECT 1 FROM pick_lists p JOIN orders o ON o.shop_id=p.shop_id
            JOIN order_items i ON i.order_id=o.order_id JOIN locations l ON l.location_id=NEW.location_id
            JOIN shop_warehouses sw ON sw.shop_id=o.shop_id AND sw.warehouse_id=l.warehouse_id
            WHERE p.pick_list_id=NEW.pick_list_id AND o.order_id=NEW.order_id
            AND i.item_id=NEW.order_item_id AND i.product_id=NEW.product_id)""",
        'packages': """NOT EXISTS (SELECT 1 FROM orders o JOIN shop_warehouses sw ON sw.shop_id=o.shop_id
            WHERE o.order_id=NEW.order_id AND sw.warehouse_id=NEW.warehouse_id)""",
        'parcel_contents': """NOT EXISTS (SELECT 1 FROM packages p JOIN order_items i ON i.order_id=p.order_id
            WHERE p.package_id=NEW.package_id AND i.item_id=NEW.item_id)""",
        'order_shipments': "NEW.package_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM packages p WHERE p.package_id=NEW.package_id AND p.order_id=NEW.order_id)",
        'dispatch_mail': """NEW.invoice_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM order_shipments s JOIN invoices i
            ON i.order_id=s.order_id WHERE s.shipment_id=NEW.shipment_id AND i.invoice_id=NEW.invoice_id)""",
    }
    for table, condition in conditions.items():
        for event in ('INSERT', 'UPDATE'):
            db.execute(f'''CREATE TRIGGER scope_{table}_{event.lower()} BEFORE {event} ON {table}
                WHEN {condition} BEGIN SELECT RAISE(ABORT,'shop_relationship_conflict'); END''')
    for table, key in (('customers','shop_id'), ('orders','shop_id'), ('pick_lists','shop_id'),
                       ('invoices','shop_id'), ('locations','warehouse_id'), ('packages','warehouse_id')):
        db.execute(f'''CREATE TRIGGER immutable_{table}_scope BEFORE UPDATE OF {key} ON {table}
            WHEN OLD.{key} != NEW.{key} BEGIN SELECT RAISE(ABORT,'immutable_business_context'); END''')
