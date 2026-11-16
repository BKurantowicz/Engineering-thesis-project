"""Shared warehouse registry with read-only validation and exclusive creation."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile

from models.database import DatabaseManager
from models.operations_schema import record_event


class WarehouseRegistry:
    def __init__(self, auth):
        self.auth = auth

    def paths(self):
        self.auth.require()
        with closing(self.auth.connect()) as db:
            return [r[0] for r in db.execute('SELECT path FROM warehouses ORDER BY path')]

    @staticmethod
    def validate(path):
        path = Path(path).resolve()
        if not path.is_file():
            raise ValueError('warehouse_invalid')
        try:
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
                if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise ValueError('warehouse_invalid')
                for table, columns in {
                    'products': {'product_id','sku','name_pl','name_en','desc_pl','desc_en','price','weight','length','width','height','is_active'},
                    'customers': {'customer_id','first_name','last_name','street','postal_code','city','email','phone','is_active'},
                    'locations': {'location_id','location_code','max_weight','max_volume','is_virtual'},
                    'inventory': {'product_id','location_id','quantity'},
                    'orders': {'order_id','customer_id','status_code','sales_snapshot','order_date','total_amount','payment_method_id','held','channel','external_ref'},
                    'order_items': {'item_id','order_id','product_id','quantity','unit_price','sale_snapshot'},
                    'pick_lists': {'pick_list_id','status','created_at'},
                    'pick_list_orders': {'pick_list_id','order_id'},
                    'pick_allocations': {'allocation_id','pick_list_id','order_id','order_item_id','product_id','location_id','quantity','reserved_quantity','picked_quantity','returned_quantity','cancelled'},
                    'inventory_transactions': {'transaction_id','product_id','location_id','quantity_change','transaction_type','created_at'},
                    'shortage_events': {'operation_id','pick_list_id','product_id','source_location_id','missing_quantity','actual_quantity','result_json'},
                    'order_shipments': {'shipment_id','order_id','package_code','shipping_type_id','package_id','tracking_number','dispatched_at'},
                    'packages': {'package_id','order_id','package_code'},
                    'parcel_contents': {'package_id','item_id','quantity'},
                    'dispatch_mail': {'shipment_id','state','detail'},
                    'invoices': {'invoice_id','invoice_number','order_id','document'},
                    'dict_order_statuses': {'status_code','name_pl','name_en'},
                    'dict_payment_methods': {'id','name_pl','name_en'},
                    'dict_shipping_methods': {'shipping_id','carrier_name'},
                    'dict_package_types': {'package_code','base_cost'},
                }.items():
                    if not columns.issubset({r[1] for r in db.execute(f'PRAGMA table_info({table})')}):
                        raise ValueError('warehouse_invalid')
        except sqlite3.Error:
            raise ValueError('warehouse_invalid') from None
        return str(path)

    def register(self, path):
        self.auth.require(True)
        path = self.validate(path)
        DatabaseManager(path)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('ATTACH DATABASE ? AS shared', (self.auth.path,))
            db.execute('BEGIN IMMEDIATE')
            exists = db.execute('SELECT 1 FROM shared.warehouses WHERE path=?', (path,)).fetchone()
            if not exists:
                db.execute('INSERT INTO shared.warehouses(path) VALUES(?)', (path,))
                record_event(db, 'WAREHOUSE_REGISTER', details=path)
        return path

    def create(self, path):
        self.auth.require(True)
        target = Path(path).resolve()
        if target.exists() or not target.name.strip() or target.suffix.lower() not in ('.db', '.sqlite', '.sqlite3'):
            raise ValueError('warehouse_exists')
        descriptor, temporary = tempfile.mkstemp(prefix='.warehouse-', suffix='.db', dir=target.parent)
        os.close(descriptor)
        temporary = Path(temporary)
        published = False
        try:
            DatabaseManager(str(temporary))
            with closing(sqlite3.connect(temporary)) as db, db:
                record_event(db, 'WAREHOUSE_CREATE', details=str(target))
            # Hard link creation fails if another process already created the name.
            os.link(temporary, target)
            published = True
            return self.register(target)
        except Exception:
            if published and target.exists() and target.samefile(temporary):
                target.unlink()
            raise
        finally:
            temporary.unlink(missing_ok=True)

    def activate(self, path):
        self.auth.require()
        path = str(Path(path).resolve())
        if path not in self.paths():
            raise ValueError('warehouse_unregistered')
        return self.validate(path)
