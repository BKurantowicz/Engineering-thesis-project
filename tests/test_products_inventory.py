"""Catalogue, availability and capacity guards against isolated persistence."""

from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import gc
import os
from pathlib import Path
import sqlite3
import tempfile
from threading import Barrier
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QDialog

from controllers.inventory_controller import WarehouseError
from controllers.product_controller import ProductController
from models.database import DatabaseManager
from utils.theme_manager import ThemeManager
from utils.translations import translator
from views.products.product_dialog import ProductDialog, StockDialog
from views.products.products_view import ProductsView


ROOT = Path(__file__).resolve().parents[1]
PRODUCT = dict(sku="BOX-1", name_pl="Pudełko", name_en="Box", price="12.30", weight="2.5", length="20", width="25", height="40")


class ProductInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.addCleanup(gc.collect)
        self.db_path = str(Path(self.temp_dir.name) / "products.db")
        DatabaseManager(self.db_path)
        self.controller = ProductController(self.db_path)
        self.inventory = self.controller.inventory
        self.sql("INSERT INTO locations (location_id, location_code, max_weight, max_volume, is_virtual) VALUES (1, 'A', 500, 1, 0), (2, 'B', 750, 1.5, 0), (3, 'braki', 9999, 9999, 1)")
        self.product_id = self.controller.save_product(PRODUCT)
        self.widgets = []
        self.addCleanup(self.close_widgets)
        self.addCleanup(self.app.setStyleSheet, self.app.styleSheet())
        for name in ("theme_name", "font_size_name"):
            self.addCleanup(self.app.setProperty, name, self.app.property(name))

    def close_widgets(self):
        for widget in self.widgets:
            widget.close()
            widget.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def sql(self, statement, parameters=()):
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            return connection.execute(statement, parameters).fetchall()

    def dump(self):
        with closing(sqlite3.connect(self.db_path)) as connection:
            return list(connection.iterdump())

    def assert_rejected_unchanged(self, code, action):
        before = self.dump()
        with self.assertRaises(WarehouseError) as error:
            action()
        self.assertEqual(error.exception.code, code)
        self.assertEqual(self.dump(), before)
        return error.exception

    def test_catalogue_only_zero_price_optional_measurements_and_identity_preservation(self):
        product_id = self.controller.save_product(dict(sku="CAT", name_pl="Katalog", name_en="Catalogue", price="0"))
        self.assertEqual(self.controller.get_product(product_id)["weight"], 0)
        self.assertEqual(self.sql("SELECT * FROM inventory"), [])
        self.controller.save_product(dict(PRODUCT, sku="CAT", price="0", name_en="Edited"), product_id)
        self.assertEqual(ProductController(self.db_path).get_product(product_id)["name_en"], "Edited")
        self.assertEqual(self.controller.get_product(product_id)["price"], 0)

    def test_invalid_master_data_and_case_variant_skus_leave_database_unchanged(self):
        for field in ("sku", "name_pl", "name_en", "price"):
            self.assert_rejected_unchanged("required", lambda field=field: self.controller.save_product(dict(PRODUCT, **{field: ""})))
        for price, code in (("-1", "invalid_number"), ("nan", "invalid_number"), ("abc", "invalid_number"), ("1.234", "price_precision")):
            self.assert_rejected_unchanged(code, lambda price=price: self.controller.save_product(dict(PRODUCT, sku="NEW", price=price)))
        self.assert_rejected_unchanged("duplicate_sku", lambda: self.controller.save_product(dict(PRODUCT, sku="box-1")))
        self.controller.save_product(dict(PRODUCT, sku="box-1"), self.product_id)
        self.assertEqual(self.controller.get_product(self.product_id)["sku"], "box-1")

    def test_simultaneous_case_variant_sku_creation_and_legacy_collisions(self):
        barrier = Barrier(2)
        def save(sku):
            barrier.wait()
            try:
                return ProductController(self.db_path).save_product(dict(PRODUCT, sku=sku))
            except WarehouseError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, ("Case", "cASE")))
        self.assertEqual(results.count("duplicate_sku"), 1)
        self.sql("INSERT INTO products (sku, name_pl, name_en, price) VALUES ('box-1', 'Stary', 'Legacy', 1)")
        before = self.dump()
        self.assertEqual(self.controller.get_sku_conflicts(), [[self.product_id, 3]])
        self.assert_rejected_unchanged("duplicate_sku", lambda: self.controller.save_product(PRODUCT, self.product_id))
        self.assertEqual(self.dump(), before)

    def test_exact_capacity_adds_incrementally_and_overflow_suggests_whole_quantity_racks(self):
        self.inventory.add_stock(self.product_id, 1, 20)
        self.inventory.add_stock(self.product_id, 1, 30)
        self.assertEqual(self.sql("SELECT quantity FROM inventory WHERE location_id = 1"), [(50,)])
        error = self.assert_rejected_unchanged("capacity_exceeded", lambda: self.inventory.add_stock(self.product_id, 1, 1))
        self.assertEqual(error.details["constraints"], ["volume"])
        self.assertEqual(error.details["alternatives"], ["B"])
        self.inventory.add_stock(self.product_id, 2, 75)
        error = self.assert_rejected_unchanged("capacity_exceeded", lambda: self.inventory.add_stock(self.product_id, 1, 1))
        self.assertEqual(error.details["alternatives"], [])
        self.assertEqual(self.sql("SELECT SUM(quantity_change) FROM inventory_transactions"), [(125,)])

    def test_weight_limit_independent_missing_data_virtual_target_and_bad_quantity(self):
        self.sql("UPDATE locations SET max_weight = 5 WHERE location_id = 1")
        self.inventory.add_stock(self.product_id, 1, 2)
        error = self.assert_rejected_unchanged("capacity_exceeded", lambda: self.inventory.add_stock(self.product_id, 1, 1))
        self.assertEqual(error.details["constraints"], ["weight"])
        for quantity in (0, -1, 1.5, True):
            self.assert_rejected_unchanged("positive_quantity", lambda quantity=quantity: self.inventory.add_stock(self.product_id, 2, quantity))
        self.assert_rejected_unchanged("physical_location_required", lambda: self.inventory.add_stock(self.product_id, 3, 1))
        self.sql("UPDATE locations SET max_weight = 0 WHERE location_id = 2")
        self.assert_rejected_unchanged("capacity_data", lambda: self.inventory.add_stock(self.product_id, 2, 1))
        self.sql("UPDATE products SET height = 0 WHERE product_id = ?", (self.product_id,))
        self.assert_rejected_unchanged("measurements_required", lambda: self.inventory.add_stock(self.product_id, 2, 1))

    def test_competing_placements_cannot_overfill_rack(self):
        self.inventory.add_stock(self.product_id, 1, 49)
        barrier = Barrier(2)
        def place(_):
            barrier.wait()
            try:
                ProductController(self.db_path).inventory.add_stock(self.product_id, 1, 1)
                return "saved"
            except WarehouseError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(place, (1, 2)))
        self.assertCountEqual(results, ["saved", "capacity_exceeded"])
        self.assertEqual(self.sql("SELECT quantity FROM inventory WHERE location_id = 1"), [(50,)])

    def test_measurement_edit_checks_every_occupied_rack_and_preserves_order_history(self):
        self.inventory.add_stock(self.product_id, 1, 10)
        self.inventory.add_stock(self.product_id, 2, 75)
        self.sql("INSERT INTO orders (order_id) VALUES (1)")
        self.sql("INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (1, ?, 2, 12.30)", (self.product_id,))
        self.assert_rejected_unchanged("capacity_exceeded", lambda: self.controller.save_product(dict(PRODUCT, height="41"), self.product_id))
        self.assert_rejected_unchanged("capacity_data", lambda: self.controller.save_product(dict(PRODUCT, weight=""), self.product_id))
        self.controller.save_product(dict(PRODUCT, name_en="Updated", price="99"), self.product_id)
        self.assertEqual(self.sql("SELECT quantity, unit_price FROM order_items"), [(2, 12.3)])
        self.assertEqual(self.sql("SELECT SUM(quantity) FROM inventory"), [(85,)])

    def test_availability_excludes_virtual_reservations_and_inactive_sales_and_filters_combine(self):
        self.inventory.add_stock(self.product_id, 1, 20)
        self.inventory.add_stock(self.product_id, 2, 10)
        self.sql("INSERT INTO inventory VALUES (?, 3, 100)", (self.product_id,))
        self.sql("INSERT INTO orders (order_id) VALUES (1)")
        self.sql("INSERT INTO order_items (item_id, order_id, product_id, quantity, unit_price) VALUES (1, 1, ?, 4, 12.30)", (self.product_id,))
        self.sql("INSERT INTO pick_lists (pick_list_id) VALUES (1)")
        self.sql("INSERT INTO pick_allocations (pick_list_id, order_id, order_item_id, product_id, location_id, quantity, reserved_quantity) VALUES (1, 1, 1, ?, 1, 4, 4)", (self.product_id,))
        self.assertEqual(self.controller.get_products()[0]["available"], 26)
        self.assertEqual(self.controller.get_products(location_id=1)[0]["available"], 16)
        self.assertEqual(len(self.controller.get_products("PUDEŁKO", location_id=1, min_quantity=16, max_quantity=16, min_price="12.30", max_price="12.30")), 1)
        self.assertEqual(self.controller.get_products("Box", location_id=1, min_quantity=17), [])
        self.assert_rejected_unchanged("inverted_range", lambda: self.controller.get_products(min_price=20, max_price=10))
        self.assert_rejected_unchanged("integer_range", lambda: self.controller.get_products(min_quantity="1.5"))
        self.controller.set_active(self.product_id, False)
        product = self.controller.get_products()[0]
        self.assertEqual((product["available"], product["physical"], product["reserved"]), (0, 30, 4))
        self.assertEqual(self.controller.get_products(min_quantity=1), [])
        self.assertEqual(len(self.controller.get_products(max_quantity=0)), 1)

    def test_referenced_delete_and_new_item_guards_preserve_history(self):
        self.sql("INSERT INTO orders (order_id) VALUES (1)")
        self.sql("INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (1, ?, 2, 12.30)", (self.product_id,))
        self.assert_rejected_unchanged("product_referenced", lambda: self.controller.delete_product(self.product_id))
        self.controller.set_active(self.product_id, False)
        before = self.dump()
        with self.assertRaisesRegex(sqlite3.IntegrityError, "inactive_product"):
            self.sql("INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (1, ?, 1, 1)", (self.product_id,))
        with self.assertRaisesRegex(sqlite3.IntegrityError, "product_referenced"):
            self.sql("DELETE FROM products WHERE product_id = ?", (self.product_id,))
        self.assertEqual(self.dump(), before)
        self.sql("UPDATE orders SET status_code = 'IN_PROGRESS' WHERE order_id = 1")
        self.controller.set_active(self.product_id, True)
        other = self.controller.save_product(dict(PRODUCT, sku="UNUSED"))
        self.controller.delete_product(other)
        self.assertEqual(len(self.controller.get_products()), 1)

    def test_forms_validate_cancel_save_once_and_show_capacity_alternatives_in_both_languages(self):
        for language in ("en", "pl"):
            trans = translator(language, str(ROOT / "utils"))
            for theme in ("light", "dark", "modern"):
                ThemeManager.apply_theme(self.app, theme, "medium")
                view = ProductsView(trans, self.controller)
                self.widgets.append(view)
                view.resize(1100, 650)
                view.show()
                self.app.processEvents()
                self.assertEqual(view.palette().color(QPalette.Window), QColor(ThemeManager.get_palette(theme)["bg_main"]))
                view.search_input.setText("no-match")
                self.assertEqual(view.message.text(), trans.t("prod_no_matches"))
                view.search_input.clear()
                self.assertEqual(view.table.rowCount(), 1)
                view.table.selectRow(0)
                self.assertEqual(view.selected_id(), self.product_id)
                dialog = ProductDialog(trans, self.controller, self.product_id)
                self.widgets.append(dialog)
                before = self.dump()
                dialog.fields["price"].setText("1.234")
                dialog.save()
                self.assertEqual(dialog.error_label.text(), trans.t("wh_error_price_precision"))
                dialog.reject()
                self.assertEqual(self.dump(), before)
        self.inventory.add_stock(self.product_id, 1, 50)
        dialog = StockDialog(trans, self.controller, self.product_id)
        self.widgets.append(dialog)
        dialog.save()
        self.assertIn("B", dialog.error_label.text())
        self.assertFalse(dialog.saved)
        dialog.location.setCurrentIndex(dialog.location.findData(2))
        dialog.save()
        dialog.save()
        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertEqual(self.sql("SELECT quantity FROM inventory WHERE location_id = 2"), [(1,)])


if __name__ == "__main__":
    unittest.main()
