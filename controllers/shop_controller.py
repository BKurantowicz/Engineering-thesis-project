"""Administrator configuration and revocable contexts in the unified database."""
from contextlib import closing
from decimal import Decimal, InvalidOperation
import json
import sqlite3

from controllers.auth_controller import AuthError


class ShopController:
    def __init__(self, auth):
        self.auth = auth

    def connect(self):
        db = sqlite3.connect(self.auth.path)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        return db

    def _require(self, db, admin=False):
        """Recheck under the same transaction lock used for configuration writes."""
        session = self.auth.require(admin)
        row = db.execute('SELECT role,version FROM accounts WHERE user_id=?', (session['user_id'],)).fetchone()
        if not row or row['version'] != session['version'] or (admin and row['role'] != 'admin'):
            raise AuthError('auth_forbidden')
        return session

    def shops(self):
        with closing(self.connect()) as db:
            session = self._require(db)
            return [dict(r) for r in db.execute('''SELECT s.* FROM shops s WHERE
                ?='admin' OR EXISTS(SELECT 1 FROM accounts a WHERE a.user_id=? AND a.all_shops=1)
                OR EXISTS(SELECT 1 FROM account_shops a WHERE a.user_id=? AND a.shop_id=s.shop_id)
                ORDER BY s.name_key,s.shop_id''', (session['role'],session['user_id'],session['user_id']))]

    def require_shop(self, db, shop_id):
        session = self._require(db)
        row = db.execute('''SELECT s.shop_id FROM shops s WHERE s.shop_id=? AND
            (?='admin' OR EXISTS(SELECT 1 FROM accounts a WHERE a.user_id=? AND a.all_shops=1)
            OR EXISTS(SELECT 1 FROM account_shops a WHERE a.user_id=? AND a.shop_id=s.shop_id))''',
            (shop_id,session['role'],session['user_id'],session['user_id'])).fetchone()
        if not row:
            raise AuthError('shop_forbidden')

    def last_context(self):
        with closing(self.connect()) as db:
            session = self._require(db)
            row = db.execute('SELECT value FROM app_state WHERE key=?', ('context:'+session['user_id'],)).fetchone()
            return json.loads(row[0]) if row else [None,None]

    def remember_context(self):
        with closing(self.connect()) as db, db:
            session = self._require(db)
            self.require_shop(db,self.auth.shop_id)
            db.execute('INSERT INTO app_state VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                       ('context:'+session['user_id'],json.dumps([self.auth.shop_id,self.auth.warehouse_id])))

    @staticmethod
    def _name(value):
        name = value.strip() if isinstance(value, str) else ''
        if not name or len(name) > 100 or any(ord(c) < 32 for c in name):
            raise ValueError('shop_name_invalid')
        return name, name.casefold()

    def save_shop(self, name, shop_id=None):
        name, key = self._name(name)
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self._require(db, True)
            if shop_id is None:
                shop_id = db.execute('INSERT INTO shops(name,name_key) VALUES(?,?)', (name,key)).lastrowid
                db.execute('INSERT INTO shop_settings(shop_id) VALUES(?)', (shop_id,))
            elif db.execute('UPDATE shops SET name=?,name_key=? WHERE shop_id=?', (name,key,shop_id)).rowcount != 1:
                raise ValueError('shop_not_found')
            return shop_id

    def create_warehouse(self, name):
        name, key = self._name(name)
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self._require(db, True)
            return db.execute('INSERT INTO physical_warehouses(name,name_key) VALUES(?,?)', (name,key)).lastrowid

    def warehouses(self, shop_id=None):
        with closing(self.connect()) as db:
            if shop_id is None:
                self._require(db, True)
                return [dict(r) for r in db.execute('SELECT * FROM physical_warehouses ORDER BY name_key,warehouse_id')]
            self.require_shop(db, shop_id)
            return [dict(r) for r in db.execute('''SELECT w.* FROM physical_warehouses w JOIN shop_warehouses s USING(warehouse_id)
                WHERE s.shop_id=? ORDER BY w.name_key,w.warehouse_id''', (shop_id,))]

    def assign_warehouses(self, shop_id, warehouse_ids):
        ids = set(warehouse_ids)
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self._require(db, True)
            if not db.execute('SELECT 1 FROM shops WHERE shop_id=?', (shop_id,)).fetchone():
                raise ValueError('shop_not_found')
            existing = {r[0] for r in db.execute('SELECT warehouse_id FROM physical_warehouses')}
            if not ids.issubset(existing):
                raise ValueError('warehouse_invalid')
            previous = {r[0] for r in db.execute('SELECT warehouse_id FROM shop_warehouses WHERE shop_id=?', (shop_id,))}
            for warehouse_id in previous - ids:
                pending = db.execute('''SELECT 1 FROM pick_allocations a JOIN orders o USING(order_id)
                    JOIN locations l USING(location_id) WHERE o.shop_id=? AND l.warehouse_id=?
                    AND (a.reserved_quantity>0 OR (a.picked_quantity>a.returned_quantity
                        AND o.status_code NOT IN ('SHIPPED','CANCELLED'))) LIMIT 1''', (shop_id,warehouse_id)).fetchone()
                parcels = db.execute('''SELECT 1 FROM packages p JOIN orders o USING(order_id)
                    LEFT JOIN order_shipments s ON s.package_id=p.package_id WHERE o.shop_id=?
                    AND p.warehouse_id=? AND s.dispatched_at IS NULL LIMIT 1''', (shop_id,warehouse_id)).fetchone()
                if pending or parcels:
                    raise ValueError('warehouse_assignment_busy')
            db.executemany('DELETE FROM shop_warehouses WHERE shop_id=? AND warehouse_id=?', [(shop_id,w) for w in previous-ids])
            db.executemany('INSERT INTO shop_warehouses VALUES(?,?)', [(shop_id,w) for w in ids-previous])

    def assignments(self, user_id):
        with closing(self.connect()) as db:
            self._require(db, True)
            row = db.execute("SELECT all_shops FROM accounts WHERE user_id=? AND role='employee'", (user_id,)).fetchone()
            if not row:
                raise ValueError('auth_forbidden')
            return bool(row[0]), [r[0] for r in db.execute('SELECT shop_id FROM account_shops WHERE user_id=? ORDER BY shop_id', (user_id,))]

    def assign_employee(self, user_id, shop_ids, *, all_shops=False):
        if not isinstance(all_shops, bool):
            raise ValueError('shop_assignment_invalid')
        ids = set(shop_ids)
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self._require(db, True)
            if not ids.issubset({r[0] for r in db.execute('SELECT shop_id FROM shops')}):
                raise ValueError('shop_not_found')
            if db.execute("UPDATE accounts SET all_shops=?,version=version+1 WHERE user_id=? AND role='employee'", (int(all_shops),user_id)).rowcount != 1:
                raise AuthError('auth_forbidden')
            db.execute('DELETE FROM account_shops WHERE user_id=?', (user_id,))
            db.executemany('INSERT INTO account_shops VALUES(?,?)', [(user_id,s) for s in ids])

    def settings(self, shop_id):
        with closing(self.connect()) as db:
            self.require_shop(db, shop_id)
            return json.loads(db.execute('SELECT configuration FROM shop_settings WHERE shop_id=?', (shop_id,)).fetchone()[0])

    def save_settings(self, shop_id, configuration):
        values = {k: v for k, v in configuration.items() if k in ('company', 'company_info', 'email_smtp')}
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self._require(db, True)
            if db.execute('UPDATE shop_settings SET configuration=? WHERE shop_id=?', (json.dumps(values,ensure_ascii=False),shop_id)).rowcount != 1:
                raise ValueError('shop_not_found')

    def set_price(self, shop_id, product_id, price):
        cents = None
        if price is not None:
            try:
                value = Decimal(str(price))
                if not value.is_finite() or value < 0 or value*100 != (value*100).to_integral_value():
                    raise ValueError('price')
                cents = int(value*100)
                if cents > 999999999999999:
                    raise ValueError('price')
            except (InvalidOperation, TypeError):
                raise ValueError('price') from None
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self.require_shop(db, shop_id)
            if not db.execute('SELECT 1 FROM products WHERE product_id=?', (product_id,)).fetchone():
                raise ValueError('product_not_found')
            if cents is None:
                db.execute('DELETE FROM shop_prices WHERE shop_id=? AND product_id=?', (shop_id,product_id))
            else:
                db.execute('''INSERT INTO shop_prices VALUES(?,?,?) ON CONFLICT(shop_id,product_id)
                    DO UPDATE SET price_cents=excluded.price_cents''', (shop_id,product_id,cents))

    def price(self, shop_id, product_id):
        with closing(self.connect()) as db:
            self.require_shop(db, shop_id)
            row = db.execute('''SELECT COALESCE(s.price_cents/100.0,p.price) FROM products p
                LEFT JOIN shop_prices s ON s.product_id=p.product_id AND s.shop_id=? WHERE p.product_id=?''', (shop_id,product_id)).fetchone()
            if row is None:
                raise ValueError('product_not_found')
            return row[0]
