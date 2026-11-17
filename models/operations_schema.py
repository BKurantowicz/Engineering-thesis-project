"""Additive administration, receipt identity and operation history schema."""


def initialize_operations_schema(cursor):
    columns = {row[1] for row in cursor.execute('PRAGMA table_info(locations)')}
    if 'is_archived' not in columns:
        cursor.execute('ALTER TABLE locations ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0')
    cursor.execute('''CREATE TABLE IF NOT EXISTS operation_history(
        event_id INTEGER PRIMARY KEY, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        operation TEXT NOT NULL, operation_id TEXT, product_id INTEGER, location_id INTEGER,
        quantity INTEGER, actor_id TEXT, actor_login TEXT, details TEXT NOT NULL DEFAULT '',
        transaction_id INTEGER UNIQUE)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS delivery_receipts(
        delivery_number TEXT PRIMARY KEY, operation_id TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')


def record_event(connection, operation, product_id=None, location_id=None, quantity=None,
                 operation_id=None, details='', transaction_id=None):
    from controllers.auth_controller import actor
    identity = actor()
    connection.execute('''INSERT INTO operation_history(operation,operation_id,product_id,location_id,
        quantity,actor_id,actor_login,details,transaction_id) VALUES(?,?,?,?,?,?,?,?,?)''',
        (operation, operation_id, product_id, location_id, quantity,
         identity['user_id'] if identity else None, identity['login'] if identity else None, details, transaction_id))
