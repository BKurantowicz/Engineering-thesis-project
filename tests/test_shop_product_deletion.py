"""Delete unused shared products without losing prices on rejected operations."""
from contextlib import closing
import sqlite3
import unittest

import test_shop_operations as operations
from controllers.product_controller import ProductController


class ShopProductDeletionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = operations.ShopOperationsTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.controller = ProductController(self.fixture.path)
        data = dict(sku='UNUSED', name_pl='Nieuzywany', name_en='Unused', price='10')
        self.unused = self.controller.save_product(data)
        self.controller.save_product(dict(data, price='11'), self.unused)
        self.fixture.shop.set_price(self.fixture.b, self.unused, '12')

    def test_unused_edited_product_and_all_its_shop_prices_are_deleted(self):
        f = self.fixture
        f.shop.set_price(1, f.product, '20')
        f.shop.set_price(f.b, f.product, '30')
        with closing(sqlite3.connect(f.path)) as db:
            protected = db.execute('SELECT * FROM shop_prices WHERE product_id=?', (f.product,)).fetchall()
            stock = db.execute('SELECT * FROM inventory ORDER BY product_id,location_id').fetchall()
        self.controller.delete_product(self.unused)
        with closing(sqlite3.connect(f.path)) as db:
            self.assertIsNone(db.execute('SELECT 1 FROM products WHERE product_id=?', (self.unused,)).fetchone())
            self.assertEqual(db.execute('SELECT * FROM shop_prices WHERE product_id=?', (self.unused,)).fetchall(), [])
            self.assertEqual(db.execute('SELECT * FROM shop_prices WHERE product_id=?', (f.product,)).fetchall(), protected)
            self.assertEqual(db.execute('SELECT * FROM inventory ORDER BY product_id,location_id').fetchall(), stock)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_referenced_product_rejection_preserves_prices_and_business_data(self):
        f = self.fixture
        f.shop.set_price(1, f.product, '20')
        f.shop.set_price(f.b, f.product, '30')
        f.order(1)
        before = f.dump()
        with self.assertRaisesRegex(ValueError, 'product_referenced'):
            self.controller.delete_product(f.product)
        self.assertEqual(f.dump(), before)

    def test_late_delete_failure_restores_product_and_all_shop_prices(self):
        f = self.fixture
        with closing(sqlite3.connect(f.path)) as db, db:
            db.execute("""CREATE TRIGGER injected_delete_failure BEFORE DELETE ON products
                BEGIN SELECT RAISE(ABORT,'injected deletion failure'); END""")
        before = f.dump()
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'injected deletion failure'):
            self.controller.delete_product(self.unused)
        self.assertEqual(f.dump(), before)


if __name__ == '__main__':
    unittest.main()
