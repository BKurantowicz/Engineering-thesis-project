"""Customer retirement preserves history and blocks only new orders."""

from contextlib import closing
import gc
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QMessageBox

from controllers.customer_controller import CustomerController, CustomerValidationError
from controllers.order_controller import OrderController, OrderValidationError
from models.database import DatabaseManager
from utils.theme_manager import ThemeManager
from utils.translations import translator
from views.customers.customers_view import CustomersView


ROOT = Path(__file__).resolve().parents[1]


class CustomerLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.addCleanup(gc.collect)
        self.db_path = str(Path(self.temp_dir.name) / "lifecycle.db")
        DatabaseManager(self.db_path)
        self.controller = CustomerController(self.db_path)
        self.orders = OrderController(self.db_path)
        self.first = self.controller.save_customer(dict(first_name="Anna", last_name="Zulu", street="Street 1", postal_code="00-001", city="Warsaw"))
        self.second = self.controller.save_customer(dict(first_name="Betty", last_name="Alpha", street="Street 2", postal_code="10-002", city="Gdansk"))
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

    def new_order(self, customer_id):
        return self.orders.add_order(customer_id, 1, None, 50, {"name": "Original recipient", "street": "Old Street", "city": "Old city"})

    def open_view(self, language):
        view = CustomersView(translator(language, str(ROOT / "utils")), self.controller)
        self.widgets.append(view)
        view.resize(1100, 600)
        view.show()
        self.app.processEvents()
        return view

    def test_migration_defaults_legacy_customers_to_active_and_preserves_later_state(self):
        legacy = str(Path(self.temp_dir.name) / "legacy.db")
        with closing(sqlite3.connect(legacy)) as connection, connection:
            connection.execute("CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, first_name TEXT, last_name TEXT, email TEXT, street TEXT, postal_code TEXT, city TEXT, created_at TEXT, phone TEXT)")
            connection.execute("INSERT INTO customers VALUES (7, 'Legacy', 'Name', NULL, 'Road', 'Code', 'City', '2025-01-01', '123')")
        DatabaseManager(legacy)
        customer = dict(CustomerController(legacy).get_customer(7))
        self.assertEqual(customer["is_active"], 1)
        self.assertEqual(customer["phone"], "123")
        CustomerController(legacy).set_active(7, False)
        DatabaseManager(legacy)
        self.assertEqual(dict(CustomerController(legacy).get_customer(7)), dict(customer, is_active=0))

    def test_delete_only_unreferenced_selected_customer(self):
        order_id = self.new_order(self.first)
        before = self.dump()
        with self.assertRaises(CustomerValidationError) as error:
            self.controller.delete_customer(self.first)
        self.assertEqual(error.exception.code, "referenced")
        self.assertEqual(self.dump(), before)
        self.controller.delete_customer(self.second)
        self.assertEqual([row["customer_id"] for row in self.controller.get_customers()], [self.first])
        self.assertEqual(self.sql("SELECT customer_id FROM orders WHERE order_id = ?", (order_id,)), [(self.first,)])

    def test_database_guards_apply_even_when_foreign_keys_are_disabled(self):
        self.new_order(self.first)
        self.controller.set_active(self.first, False)
        before = self.dump()
        with self.assertRaisesRegex(sqlite3.IntegrityError, "customer_referenced"):
            self.sql("DELETE FROM customers WHERE customer_id = ?", (self.first,))
        with self.assertRaisesRegex(sqlite3.IntegrityError, "inactive_customer"):
            self.sql("INSERT INTO orders (customer_id) VALUES (?)", (self.first,))
        self.assertEqual(self.dump(), before)

    def test_deactivation_blocks_new_orders_reactivation_restores_them_and_edit_keeps_state(self):
        self.controller.set_active(self.first, False)
        before = self.dump()
        with self.assertRaises(OrderValidationError) as error:
            self.new_order(self.first)
        self.assertEqual(error.exception.code, "inactive_customer")
        self.assertEqual(self.dump(), before)
        customer = dict(self.controller.get_customer(self.first))
        customer["city"] = "Updated city"
        self.controller.save_customer(customer, self.first)
        self.assertEqual(self.controller.get_customer(self.first)["is_active"], 0)
        self.controller.set_active(self.first, True)
        new_id = self.new_order(self.first)
        self.assertEqual(self.sql("SELECT customer_id FROM orders WHERE order_id = ?", (new_id,)), [(self.first,)])

    def test_existing_orders_and_history_remain_readable_and_can_progress(self):
        order_id = self.new_order(self.first)
        self.sql("INSERT INTO products (product_id, sku, name_pl, name_en, price) VALUES (1, 'P1', 'Produkt', 'Product', 25)")
        self.sql("INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (?, 1, 2, 25)", (order_id,))
        self.sql("INSERT INTO invoices (order_id, invoice_number, billing_street) VALUES (?, 'INV-1', 'Historical address')", (order_id,))
        before_orders = self.sql("SELECT * FROM orders")
        before_items = self.sql("SELECT * FROM order_items")
        before_invoices = self.sql("SELECT * FROM invoices")
        self.controller.set_active(self.first, False)
        self.assertEqual(self.sql("SELECT * FROM orders"), before_orders)
        self.assertEqual(self.sql("SELECT * FROM order_items"), before_items)
        self.assertEqual(self.sql("SELECT * FROM invoices"), before_invoices)
        self.assertEqual(self.orders.get_orders()[0]["first_name"], "Anna")
        self.assertEqual(self.orders.get_order_items(order_id)[0]["quantity"], 2)
        for status in ("IN_PROGRESS", "PACKED", "SHIPPED"):
            self.sql("UPDATE orders SET status_code = ? WHERE order_id = ?", (status, order_id))
            self.assertEqual(self.sql("SELECT status_code FROM orders WHERE order_id = ?", (order_id,)), [(status,)])

    def test_missing_record_and_failed_activity_update_leave_data_unchanged(self):
        before = self.dump()
        for operation in (lambda: self.controller.delete_customer(999), lambda: self.controller.set_active(999, False)):
            with self.assertRaises(CustomerValidationError) as error:
                operation()
            self.assertEqual(error.exception.code, "not_found")
        self.assertEqual(self.dump(), before)
        self.sql("CREATE TRIGGER reject_activity BEFORE UPDATE OF is_active ON customers BEGIN SELECT RAISE(ABORT, 'storage rejected'); END")
        before = self.dump()
        with self.assertRaises(sqlite3.IntegrityError):
            self.controller.set_active(self.first, False)
        self.assertEqual(self.dump(), before)

    def test_translated_actions_target_stable_identity_and_preserve_blocked_data(self):
        self.new_order(self.first)
        for language in ("en", "pl"):
            view = self.open_view(language)
            for theme in ("light", "dark", "modern"):
                with self.subTest(language=language, theme=theme):
                    ThemeManager.apply_theme(self.app, theme, "medium")
                    self.app.processEvents()
                    self.assertEqual(view.palette().color(QPalette.Window), QColor(ThemeManager.get_palette(theme)["bg_main"]))
                    view.load_customers(self.first)
                    self.assertEqual(view.selected_customer_id(), self.first)
                    self.assertEqual(view.table.currentRow(), 1)  # Sorted by name, not primary key.
                    view.active_button.click()
                    self.assertEqual(self.controller.get_customer(self.first)["is_active"], 0)
                    self.assertEqual(self.controller.get_customer(self.second)["is_active"], 1)
                    self.assertEqual(view.active_button.text(), view.t("cust_reactivate"))
                    self.assertEqual(view.table.item(1, view.COLUMNS.index("is_active")).text(), view.t("cust_inactive"))
                    before = self.dump()
                    with patch.object(view, "confirm_delete", return_value=True):
                        view.delete_button.click()
                    self.assertEqual(self.dump(), before)
                    self.assertEqual(view.message.text(), view.t("cust_error_referenced"))
                    view.load_customers(self.first)
                    view.active_button.click()
                    self.assertEqual(self.controller.get_customer(self.first)["is_active"], 1)
                    self.assertEqual(view.styleSheet(), "")

    def test_confirmation_cancel_is_non_destructive_and_confirmed_delete_refreshes_selection(self):
        view = self.open_view("pl")
        view.load_customers(self.second)
        before = self.dump()
        def cancel_prompt():
            prompt = self.app.activeModalWidget()
            self.assertIsInstance(prompt, QMessageBox)
            self.assertEqual(prompt.button(QMessageBox.No).text(), view.t("cust_cancel"))
            self.assertEqual(prompt.defaultButton(), prompt.button(QMessageBox.No))
            prompt.button(QMessageBox.No).click()
        QTimer.singleShot(0, cancel_prompt)
        view.delete_button.click()
        self.assertEqual(self.dump(), before)
        with patch.object(view, "confirm_delete", return_value=True):
            view.delete_button.click()
        self.assertEqual(view.table.rowCount(), 1)
        self.assertEqual(view.table.item(0, 0).data(Qt.UserRole), self.first)
        self.assertFalse(view.edit_button.isEnabled())
        self.assertFalse(view.active_button.isEnabled())
        self.assertFalse(view.delete_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
