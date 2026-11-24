"""Atomic rack administration, free withdrawals, reserved transfers and CSV receipts."""
from controllers.auth_controller import reading
from contextlib import closing
import csv
from pathlib import Path
import math
import sqlite3
import uuid

from controllers.auth_controller import authorized
from controllers.inventory_controller import InventoryController, WarehouseError, connect
from models.operations_schema import record_event
from controllers.shop_scope import insert, is_unified, warehouse_id


class WarehouseController(InventoryController):
    @authorized(True)
    def create_rack(self, code, weight, volume):
        code = code.strip()
        if not code or code.casefold() == 'braki':
            raise WarehouseError('rack_code')
        measures = [self.capacity.positive_decimal(value) for value in (weight, volume)]
        if any(v is None or not math.isfinite(float(v)) for v in measures):
            raise WarehouseError('rack_limits')
        with closing(connect(self.db_path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            if is_unified(db) and warehouse_id() is None:
                raise WarehouseError('warehouse_required')
            rack_rows = db.execute('SELECT location_code FROM scope_locations' + (' WHERE warehouse_id=?' if is_unified(db) else ''),
                                  (warehouse_id(),) if is_unified(db) else ())
            if any(r[0].strip().casefold() == code.casefold() for r in rack_rows):
                raise WarehouseError('rack_duplicate')
            lid = insert(db, 'locations', dict(location_code=code,max_weight=float(measures[0]),max_volume=float(measures[1]))).lastrowid
            record_event(db, 'RACK_CREATE', location_id=lid, details=code)
            return lid

    @staticmethod
    def physical(db, location_id):
        row = db.execute('SELECT * FROM scope_locations WHERE location_id=?', (location_id,)).fetchone()
        if not row or row['is_archived']:
            raise WarehouseError('physical_location_required')
        from controllers.capacity_controller import CapacityController
        if CapacityController.is_virtual(row):
            raise WarehouseError('physical_location_required')
        return row

    @reading
    def rack_dependencies(self, location_id, db=None):
        if db is None:
            with closing(connect(self.db_path)) as connection:
                return self.rack_dependencies(location_id, connection)
        rack = self.physical(db, location_id)
        return dict(rack=rack['location_code'], stock=db.execute(
            'SELECT COALESCE(SUM(quantity),0) FROM inventory WHERE location_id=?', (location_id,)).fetchone()[0],
            reserved=db.execute('SELECT COALESCE(SUM(reserved_quantity),0) FROM pick_allocations WHERE location_id=?',
                                (location_id,)).fetchone()[0])

    @authorized(True)
    def archive_rack(self, location_id):
        with closing(connect(self.db_path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            dependencies = self.rack_dependencies(location_id, db)
            if dependencies['stock'] or dependencies['reserved']:
                raise WarehouseError('rack_busy', **dependencies)
            db.execute('UPDATE locations SET is_archived=1 WHERE location_id=?', (location_id,))
            record_event(db, 'RACK_ARCHIVE', location_id=location_id, details=dependencies['rack'])

    def quantities(self, db, product_id, location_id):
        self.physical(db, location_id)
        physical = db.execute('SELECT quantity FROM inventory WHERE product_id=? AND location_id=?',
                              (product_id, location_id)).fetchone()
        reserved = db.execute('SELECT COALESCE(SUM(reserved_quantity),0) FROM pick_allocations WHERE product_id=? AND location_id=?',
                              (product_id, location_id)).fetchone()[0]
        return physical[0] if physical else 0, reserved

    @authorized()
    def withdraw(self, product_id, location_id, quantity, reason):
        self.positive_quantity(quantity)
        if not reason.strip():
            raise WarehouseError('reason_required')
        with closing(connect(self.db_path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            physical, reserved = self.quantities(db, product_id, location_id)
            if quantity > physical - reserved:
                raise WarehouseError('withdraw_free_only')
            self.write_change(db, product_id, location_id, -quantity, 'WITHDRAWAL', details=reason.strip())

    @authorized()
    def transfer(self, product_id, source, target, quantity):
        self.positive_quantity(quantity)
        if source == target:
            raise WarehouseError('different_racks')
        with closing(connect(self.db_path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            physical, reserved = self.quantities(db, product_id, source)
            if quantity > physical or reserved > physical:
                raise WarehouseError('insufficient_available')
            self.placement_limits(db, product_id, target, quantity)
            remaining = max(0, quantity - (physical - reserved))
            operation = uuid.uuid4().hex
            if is_unified(db):
                # Physical transfers include other shops' reservations. Persistent
                # relationship guards still reject a destination their shop cannot use.
                for event in ('INSERT','UPDATE','DELETE'):
                    db.execute(f'DROP TRIGGER IF EXISTS temp.guard_pick_allocations_{event}')
            allocations = db.execute('''SELECT a.* FROM pick_allocations a JOIN orders o USING(order_id)
                WHERE a.product_id=? AND a.location_id=? AND a.reserved_quantity>0
                ORDER BY datetime(o.order_date) DESC,o.order_id DESC,a.allocation_id DESC''', (product_id, source)).fetchall()
            for row in allocations:
                moved = min(remaining, row['reserved_quantity'])
                if not moved:
                    break
                # Retire the old outstanding instruction and create fresh identities,
                # so an already-open picking dialog cannot act on a moved allocation.
                retained = row['reserved_quantity'] - moved
                for location, amount in ((source, retained), (target, moved)):
                    if amount:
                        db.execute('''INSERT INTO pick_allocations(pick_list_id,order_id,order_item_id,
                            product_id,location_id,quantity,reserved_quantity) VALUES(?,?,?,?,?,?,?)''',
                            (row['pick_list_id'],row['order_id'],row['order_item_id'],product_id,location,amount,amount))
                if row['picked_quantity']:
                    db.execute('UPDATE pick_allocations SET quantity=picked_quantity,reserved_quantity=0 WHERE allocation_id=?',
                               (row['allocation_id'],))
                else:
                    db.execute('UPDATE pick_allocations SET reserved_quantity=0,cancelled=1 WHERE allocation_id=?',
                               (row['allocation_id'],))
                remaining -= moved
                if is_unified(db):
                    record_event(db, 'RESERVATION_TRANSFER', product_id, target, moved,
                                 operation, f'from_location={source}', order_id=row['order_id'])
            if remaining:
                raise WarehouseError('allocation_mismatch')
            self.write_change(db, product_id, source, -quantity, 'TRANSFER_OUT', operation)
            self.write_change(db, product_id, target, quantity, 'TRANSFER_IN', operation)
            return operation

    def read_delivery(self, path):
        try:
            with Path(path).open(encoding='utf-8-sig', newline='') as stream:
                reader = csv.DictReader(stream, delimiter=';', strict=True)
                if not reader.fieldnames or not {'sku','quantity','rack'}.issubset(reader.fieldnames):
                    raise WarehouseError('delivery_format')
                rows = list(reader)
                if any(None in row or any(value is None for value in row.values()) for row in rows):
                    raise WarehouseError('delivery_format')
            if not rows:
                raise WarehouseError('delivery_format')
            return rows
        except (UnicodeError, csv.Error, OSError):
            raise WarehouseError('delivery_format') from None

    def _receipt(self, db, number, rows, commit):
        number = number.strip()
        if not number:
            raise WarehouseError('delivery_number_required')
        condition = ' AND warehouse_id=?' if is_unified(db) else ''
        parameters = (number,warehouse_id()) if is_unified(db) else (number,)
        if db.execute('SELECT 1 FROM delivery_receipts WHERE delivery_number=?'+condition, parameters).fetchone():
            raise WarehouseError('delivery_duplicate')
        operation = uuid.uuid4().hex
        preview = []
        for index, row in enumerate(rows, 2):
            try:
                raw = row.get('quantity', '') or ''
                if not raw.isascii() or not raw.isdigit():
                    raise WarehouseError('positive_quantity')
                quantity = self.positive_quantity(int(raw))
                product = db.execute('SELECT product_id,name_pl,name_en FROM scope_products WHERE sku=?', (row.get('sku'),)).fetchone()
                query = 'SELECT location_id FROM scope_locations WHERE location_code=?'
                parameters = (row.get('rack'),)
                if is_unified(db):
                    query += ' AND warehouse_id=?'
                    parameters += (warehouse_id(),)
                location = db.execute(query, parameters).fetchone()
                if not product:
                    raise WarehouseError('product_not_found')
                if not location:
                    raise WarehouseError('physical_location_required')
                self.placement_limits(db, product[0], location[0], quantity)
                # Preview executes the same aggregate checks in a rolled-back transaction.
                self.write_change(db, product[0], location[0], quantity, 'CSV_RECEIPT', operation, number)
                preview.append(dict(row=index, sku=row['sku'], rack=row['rack'], quantity=quantity,
                                    name_pl=product[1], name_en=product[2]))
            except WarehouseError as error:
                raise WarehouseError(error.code, row=index, **error.details) from error
        if not preview:
            raise WarehouseError('delivery_format')
        if commit:
            if is_unified(db):
                db.execute('INSERT INTO delivery_receipts(delivery_number,operation_id,warehouse_id) VALUES(?,?,?)', (number,operation,warehouse_id()))
            else:
                db.execute('INSERT INTO delivery_receipts(delivery_number,operation_id) VALUES(?,?)', (number, operation))
        return preview

    @authorized()
    def preview_delivery(self, number, rows):
        with closing(connect(self.db_path)) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                return self._receipt(db, number, rows, False)
            finally:
                db.rollback()

    @authorized()
    def receive_delivery(self, number, rows):
        with closing(connect(self.db_path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            return self._receipt(db, number, rows, True)

    @authorized()
    def history(self, since='', until='', operation='', product='', location=''):
        with closing(connect(self.db_path)) as db:
            if is_unified(db):
                from controllers.shared_history import history
                return history(db,since,until,operation,product,location)
            return [dict(r) for r in db.execute('''WITH events AS (
                SELECT created_at,operation,operation_id,product_id,location_id,quantity,actor_login,details FROM operation_history
                UNION ALL SELECT t.created_at,t.transaction_type,NULL,t.product_id,t.location_id,t.quantity_change,NULL,''
                FROM inventory_transactions t WHERE NOT EXISTS(SELECT 1 FROM operation_history h WHERE h.transaction_id=t.transaction_id))
                SELECT e.*,p.sku,l.location_code,l.is_archived FROM events e
                LEFT JOIN scope_products p USING(product_id) LEFT JOIN scope_locations l USING(location_id)
                WHERE (?='' OR date(e.created_at)>=?) AND (?='' OR date(e.created_at)<=?)
                AND (?='' OR e.operation=?) AND (?='' OR p.sku=?) AND (?='' OR l.location_code=?)
                ORDER BY e.created_at DESC''', (since,since,until,until,operation,operation,product,product,location,location))]
