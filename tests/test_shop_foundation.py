"""Migration preservation and administrative boundaries on isolated databases."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from controllers.auth_controller import AuthController, AuthError
from controllers.shop_controller import ShopController
from models.application_migration import adapt_database, inventory, MigrationConflict, verify_preserved
from models.application_migration import complete_cutover
from models.database import DatabaseManager
from models.shop_schema import initialize_shop_schema


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source, self.target = self.root/'qa.db', self.root/'application.db'
        DatabaseManager(str(self.source))
        with closing(sqlite3.connect(self.source)) as db, db:
            db.execute("INSERT INTO products(sku,name_pl,name_en,price) VALUES('SKU','Produkt','Product',12.34)")
            db.execute("INSERT INTO locations(location_code,max_weight,max_volume) VALUES('A',100,10)")
            db.execute('INSERT INTO inventory VALUES(1,1,10)')
            db.execute("INSERT INTO customers(first_name,last_name,email,street,postal_code,city) VALUES('A','B','a@example.test','Street','00-001','City')")
            db.execute("INSERT INTO orders(customer_id,status_code,sales_snapshot) VALUES(1,'IN_PROGRESS','{\"historical\":true}')")
            db.execute('INSERT INTO order_items(order_id,product_id,quantity,unit_price) VALUES(1,1,2,10.11)')
            db.execute("INSERT INTO pick_lists(status) VALUES('PENDING')")
            db.execute('INSERT INTO pick_list_orders VALUES(1,1)')
            db.execute('''INSERT INTO pick_allocations(pick_list_id,order_id,order_item_id,product_id,location_id,quantity,reserved_quantity)
                VALUES(1,1,1,1,1,2,2)''')
            db.execute("INSERT INTO invoices(order_id,invoice_number,document) VALUES(1,'LEGACY/100','{\"immutable\":true}')")
        self.digest = hashlib.sha256(self.source.read_bytes()).hexdigest()

    def adapt(self, **options):
        return adapt_database(self.source, self.target, backup_dir=self.root/'backups', **options)

    def test_preserves_every_original_value_and_retries_without_reset(self):
        result = self.adapt()
        with closing(sqlite3.connect(self.source)) as source, closing(sqlite3.connect(self.target)) as target:
            verify_preserved(inventory(source), target)
            self.assertEqual(target.execute('SELECT shop_id FROM orders').fetchall(), [(1,)])
            self.assertEqual(target.execute('SELECT warehouse_id FROM locations').fetchall(), [(1,)])
            self.assertEqual(target.execute('SELECT COUNT(*) FROM accounts').fetchone(), (0,))
            initialize_shop_schema(target)
            with target:
                target.execute("UPDATE products SET name_en='Changed after migration' WHERE product_id=1")
        self.assertTrue(self.adapt()['reused'])
        with closing(sqlite3.connect(self.target)) as db:
            self.assertEqual(db.execute('SELECT name_en FROM products').fetchone()[0], 'Changed after migration')
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.digest)
        with closing(sqlite3.connect(result['backup'])) as db, closing(sqlite3.connect(self.source)) as source:
            self.assertEqual(inventory(db), inventory(source))

    def test_failure_between_schema_and_verification_never_publishes_partial_target(self):
        with patch('models.application_migration.verify_preserved', side_effect=RuntimeError('injected')):
            with self.assertRaisesRegex(RuntimeError, 'injected'):
                self.adapt()
        self.assertFalse(self.target.exists())
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.digest)
        self.assertEqual(len(list((self.root/'backups').glob('*.db'))), 1)
        self.assertFalse(list(self.root.glob('.application-*')))
        self.assertFalse(self.adapt()['reused'])

    def test_existing_unrelated_target_is_untouched(self):
        DatabaseManager(str(self.target))
        before = self.target.read_bytes()
        with self.assertRaisesRegex(MigrationConflict, 'existing_target_conflict'):
            self.adapt()
        self.assertEqual(self.target.read_bytes(), before)

    def test_missing_explicit_account_store_is_not_created(self):
        with self.assertRaisesRegex(MigrationConflict, 'invalid_account_source'):
            self.adapt(accounts=self.root/'missing.db')
        self.assertFalse((self.root/'missing.db').exists())
        self.assertFalse(self.target.exists())

    def test_cutover_preserves_unrelated_configuration_and_removes_only_obsolete_file(self):
        self.adapt()
        config = self.root/'config.json'
        original = {'paths':{'database':'warehouse.db','exports':'keep'},'appearance':{'theme':'modern'},'custom':'unchanged'}
        config.write_text(json.dumps(original),encoding='utf-8')
        original_bytes = config.read_bytes()
        obsolete = self.root/'warehouse.db'
        obsolete.write_bytes(b'obsolete mock data')
        unrelated = self.root/'other.db'
        unrelated.write_bytes(b'keep')
        result = complete_cutover(self.target,config,self.root/'backups',remove_obsolete=True)
        expected = dict(original,paths=dict(original['paths'],database='application.db'))
        self.assertEqual(json.loads(config.read_text()),expected)
        self.assertEqual(Path(result['configuration_backup']).read_bytes(),original_bytes)
        self.assertFalse(obsolete.exists())
        self.assertEqual(unrelated.read_bytes(),b'keep')
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),self.digest)

    def test_real_account_hashes_and_ids_are_preserved_without_new_identities(self):
        path = self.root/'accounts.db'
        auth = AuthController(path)
        uid = auth.create_account('admin','migration-password',first=True)
        with closing(sqlite3.connect(path)) as db:
            before = db.execute('SELECT * FROM accounts').fetchall()
        self.assertEqual(self.adapt(accounts=path)['accounts_migrated'], 1)
        with closing(sqlite3.connect(self.target)) as db:
            self.assertEqual(db.execute('SELECT user_id,login,password_hash,role,must_change,version FROM accounts').fetchall(), before)
            self.assertEqual(db.execute('SELECT * FROM account_shops').fetchall(), [(uid,1)])

    def test_scoped_uniqueness_and_cross_shop_relationship_guards(self):
        self.adapt()
        with closing(sqlite3.connect(self.target)) as db, db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute("INSERT INTO shops VALUES(2,'B','b')")
            db.execute("INSERT INTO physical_warehouses VALUES(2,'W2','w2')")
            db.execute('INSERT INTO shop_warehouses VALUES(2,2)')
            db.execute("INSERT INTO customers(first_name,last_name,email,street,postal_code,city,shop_id) VALUES('A','B','a@example.test','Street','00-001','City',2)")
            db.execute("INSERT INTO locations(location_code,max_weight,max_volume,warehouse_id) VALUES('A',100,10,2)")
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'shop_relationship_conflict'):
                db.execute('INSERT INTO orders(customer_id,shop_id) VALUES(1,2)')
            db.execute('INSERT INTO orders(customer_id,shop_id) VALUES(2,2)')
            db.execute("INSERT INTO invoices(order_id,shop_id,invoice_number) VALUES(2,2,'LEGACY/100')")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO invoices(order_id,shop_id,invoice_number) VALUES(2,2,'LEGACY/100')")
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'shop_relationship_conflict'):
                db.execute('INSERT INTO pick_list_orders VALUES(1,2)')
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'shop_relationship_conflict'):
                db.execute("INSERT INTO packages(order_id,package_code,warehouse_id) VALUES(1,'CUSTOM_BOX',2)")
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])


class AdministrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'application.db'
        DatabaseManager(str(self.path))
        with closing(sqlite3.connect(self.path)) as db:
            initialize_shop_schema(db)
        self.auth = AuthController(self.path)
        self.auth.create_account('admin','secret',first=True)
        self.auth.sign_in('admin','secret')
        self.ctrl = ShopController(self.auth)

    def test_independent_prices_and_base_fallback(self):
        b = self.ctrl.save_shop('Shop B')
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO products(sku,name_pl,name_en,price) VALUES('SKU','Produkt','Product',12.34)")
        self.assertEqual(self.ctrl.price(b,1), 12.34)
        self.ctrl.set_price(1,1,'20.12')
        self.assertEqual(self.ctrl.price(1,1), 20.12)
        self.assertEqual(self.ctrl.price(b,1), 12.34)
        self.ctrl.set_price(1,1,None)
        self.assertEqual(self.ctrl.price(1,1), 12.34)
        for invalid in ('NaN','Infinity','-1','1.001'):
            with self.assertRaisesRegex(ValueError,'price'):
                self.ctrl.set_price(1,1,invalid)

    def test_employee_assignment_revocation_and_future_shops(self):
        uid = self.auth.create_account('employee','temporary')
        employee = AuthController(self.path)
        employee.sign_in('employee','temporary')
        employee.change_password('temporary','employee-secret')
        ctrl = ShopController(employee)
        self.assertEqual(ctrl.shops(), [])
        self.ctrl.assign_employee(uid,[1])
        with self.assertRaises(AuthError):
            ctrl.shops()
        employee.sign_in('employee','employee-secret')
        self.assertEqual([s['shop_id'] for s in ctrl.shops()], [1])
        with self.assertRaises(AuthError):
            ctrl.assign_employee(uid,[],all_shops=True)
        with self.assertRaises(AuthError):
            ctrl.save_shop('Unauthorized')
        self.ctrl.assign_employee(uid,[],all_shops=True)
        b = self.ctrl.save_shop('New shop')
        employee.sign_in('employee','employee-secret')
        self.assertEqual({s['shop_id'] for s in ctrl.shops()}, {1,b})
        self.ctrl.assign_employee(uid,[])
        with self.assertRaises(AuthError):
            ctrl.settings(1)

    def test_warehouse_assignment_and_settings_survive_reopen(self):
        b = self.ctrl.save_shop('Shop B')
        w = self.ctrl.create_warehouse('Warehouse 2')
        self.ctrl.assign_warehouses(1,[1,w])
        self.ctrl.assign_warehouses(b,[w])
        shared = {'company':{'name':'Shared company'}, 'email_smtp':{'host':'smtp.example.test','credential_id':'same-credential'}}
        self.ctrl.save_settings(1,shared)
        self.ctrl.save_settings(b,shared)
        self.ctrl.save_settings(1,dict(shared,company={'name':'Changed'}))
        reopened = ShopController(self.auth)
        self.assertEqual({r['warehouse_id'] for r in reopened.warehouses(1)}, {1,w})
        self.assertEqual([r['warehouse_id'] for r in reopened.warehouses(b)], [w])
        self.assertEqual(reopened.settings(b), shared)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM inventory').fetchone(), (0,))


if __name__ == '__main__':
    unittest.main()
