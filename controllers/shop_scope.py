"""Connection-local read scopes and write guards for business controllers.

Reservations deliberately remain global when aggregating physical availability.
Private allocations use scope_pick_allocations instead. Maintenance has no user
context and retains access to original tables for migrations and offline fixtures.
"""
import sqlite3


class _ScopedConnection(sqlite3.Connection):
    check_context = None

    def __exit__(self, kind, value, traceback):
        if kind is None and self.in_transaction and self.check_context and not self.check_context():
            self.rollback()
            from controllers.auth_controller import AuthError
            raise AuthError('shop_context_changed')
        return super().__exit__(kind,value,traceback)


def shop_id():
    from controllers import auth_controller as auth
    return auth.runtime.shop_id if auth.runtime and auth.runtime.unified else 1


def warehouse_id():
    from controllers import auth_controller as auth
    return auth.runtime.warehouse_id if auth.runtime and auth.runtime.unified else 1


def is_unified(db):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='application_schema'").fetchone())


def insert(db, table, values):
    values = dict(values)
    if is_unified(db):
        if table in ('customers','orders','pick_lists','invoices'):
            values.setdefault('shop_id', shop_id())
        if table in ('locations','packages'):
            values.setdefault('warehouse_id', warehouse_id())
    return db.execute(f'INSERT INTO {table}({",".join(values)}) VALUES({",".join("?" for _ in values)})', tuple(values.values()))


def connect(path):
    from controllers import auth_controller as auth
    db = sqlite3.connect(path, factory=_ScopedConnection)
    db.row_factory = sqlite3.Row
    unified = db.execute("SELECT 1 FROM sqlite_master WHERE name='application_schema'").fetchone()
    current = auth.runtime
    scoped = unified and current and current.unified
    if scoped:
        try:
            current.require_context()
        except BaseException:
            db.close()
            raise
        db.execute('PRAGMA foreign_keys=ON')
        epoch, selected_shop, selected_warehouse = current.epoch,current.shop_id,current.warehouse_id
        identity = dict(current.session)
        def context_valid():
            if auth.runtime is not current or not current.session or current.epoch != epoch:
                return False
            if (current.shop_id,current.warehouse_id) != (selected_shop,selected_warehouse):
                return False
            row = db.execute('SELECT version FROM accounts WHERE user_id=?',(identity['user_id'],)).fetchone()
            return bool(row and row[0] == identity['version'])
        db.check_context = context_valid
        db.create_function('context_valid',0,context_valid)
    sid = shop_id()
    clauses = {
        'customers': f'shop_id={sid}', 'orders': f'shop_id={sid}',
        'pick_lists': f'shop_id={sid}', 'invoices': f'shop_id={sid}',
        'locations': f'warehouse_id IN (SELECT warehouse_id FROM shop_warehouses WHERE shop_id={sid})',
        'order_items': f'order_id IN (SELECT order_id FROM orders WHERE shop_id={sid})',
        'pick_list_orders': f'pick_list_id IN (SELECT pick_list_id FROM pick_lists WHERE shop_id={sid})',
        'pick_allocations': f'order_id IN (SELECT order_id FROM orders WHERE shop_id={sid})',
        'packages': f'order_id IN (SELECT order_id FROM orders WHERE shop_id={sid})',
        'order_shipments': f'order_id IN (SELECT order_id FROM orders WHERE shop_id={sid})',
        'dispatch_mail': f'shipment_id IN (SELECT shipment_id FROM order_shipments JOIN orders USING(order_id) WHERE shop_id={sid})',
        'shortage_events': f'pick_list_id IN (SELECT pick_list_id FROM pick_lists WHERE shop_id={sid})',
    }
    for table, condition in clauses.items():
        if table == 'locations' and unified:
            db.execute('''CREATE TEMP VIEW scope_locations AS SELECT l.*, w.name AS warehouse_name,
                w.name || ' / ' || l.location_code AS display_code FROM main.locations l
                JOIN physical_warehouses w USING(warehouse_id)''' + (f' WHERE {condition}' if scoped else ''))
        elif table == 'locations':
            db.execute('CREATE TEMP VIEW scope_locations AS SELECT *, location_code AS display_code FROM main.locations')
        else:
            db.execute(f'CREATE TEMP VIEW scope_{table} AS SELECT * FROM main.{table}' + (f' WHERE {condition}' if scoped else ''))
    if scoped:
        columns = [r[1] for r in db.execute('PRAGMA table_info(products)')]
        expressions = ['COALESCE(sp.price_cents/100.0,p.price) AS price' if c == 'price' else f'p.{c}' for c in columns]
        db.execute(f'''CREATE TEMP VIEW scope_products AS SELECT {','.join(expressions)} FROM main.products p
            LEFT JOIN shop_prices sp ON sp.product_id=p.product_id AND sp.shop_id={sid}''')
        for table, condition in clauses.items():
            # The same predicates, evaluated against NEW/OLD, prevent cross-shop
            # mutations even when a caller supplies a guessed primary key.
            for event, aliases in (('INSERT',('NEW',)), ('UPDATE',('OLD','NEW')), ('DELETE',('OLD',))):
                checks = ' OR '.join(f'NOT ({alias}.{condition})' for alias in aliases)
                db.execute(f'''CREATE TEMP TRIGGER guard_{table}_{event} BEFORE {event} ON main.{table}
                    WHEN NOT context_valid() OR {checks} BEGIN SELECT RAISE(ABORT,'shop_forbidden'); END''')
        for table in ('inventory','inventory_transactions'):
            for event, alias in (('INSERT','NEW'),('UPDATE','NEW'),('DELETE','OLD')):
                db.execute(f'''CREATE TEMP TRIGGER guard_{table}_{event} BEFORE {event} ON main.{table}
                    WHEN NOT EXISTS(SELECT 1 FROM scope_locations WHERE location_id={alias}.location_id)
                    BEGIN SELECT RAISE(ABORT,'warehouse_forbidden'); END''')
        for table in ('products','shop_prices','inventory','inventory_transactions','operation_history','delivery_receipts','parcel_contents'):
            for event in ('INSERT','UPDATE','DELETE'):
                db.execute(f'''CREATE TEMP TRIGGER session_{table}_{event} BEFORE {event} ON main.{table}
                    WHEN NOT context_valid() BEGIN SELECT RAISE(ABORT,'shop_context_changed'); END''')
    else:
        db.execute('CREATE TEMP VIEW scope_products AS SELECT * FROM main.products')
    return db


def settings_for_order(db, order_id):
    import json
    row = db.execute('''SELECT s.configuration FROM shop_settings s JOIN orders o USING(shop_id)
        WHERE o.order_id=?''', (order_id,)).fetchone()
    if row is None:
        raise ValueError('order')
    settings = json.loads(row[0])
    return {key:settings.get(key,{}) for key in ('company','company_info','email_smtp')}
