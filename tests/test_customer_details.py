"""Customer master-data regressions against isolated databases and real forms."""

from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import gc
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from threading import Barrier
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox

from controllers.customer_controller import CustomerController, CustomerValidationError
from main import MainWindow
from models.database import DatabaseManager
from utils.theme_manager import ThemeManager
from utils.translations import translator
from views.customers.customer_dialog import CustomerDialog
from views.customers.customers_view import CustomersView


ROOT = Path(__file__).resolve().parents[1]
VALID = {
    "first_name": "Anna", "last_name": "Nowak", "street": "Main Street 10",
    "postal_code": "00-001", "city": "Warsaw", "email": "anna@example.test", "phone": "+48 123 456 789",
}


class CustomerDetailsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        previous_directory = Path.cwd()
        os.chdir(self.temp_dir.name)
        self.addCleanup(os.chdir, previous_directory)
        self.addCleanup(gc.collect)
        self.widgets = []
        self.addCleanup(self.close_widgets)
        self.addCleanup(self.app.setStyleSheet, self.app.styleSheet())
        for name in ("theme_name", "font_size_name"):
            self.addCleanup(self.app.setProperty, name, self.app.property(name))
        self.db_path = Path(self.temp_dir.name) / "customers.db"
        DatabaseManager(str(self.db_path))
        self.controller = CustomerController(str(self.db_path))
        self.translator = translator("en", str(ROOT / "utils"))

    def close_widgets(self):
        for widget in self.widgets:
            widget.close()
            widget.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def database_dump(self, path=None):
        with closing(sqlite3.connect(path or self.db_path)) as connection:
            return list(connection.iterdump())

    def insert_fixture_customer(self):
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            return connection.execute(
                "INSERT INTO customers (first_name, last_name, street, postal_code, city, email, phone) VALUES (?, ?, ?, ?, ?, ?, ?)",
                tuple(VALID[field] for field in self.controller.FIELDS),
            ).lastrowid

    def open_dialog(self, language="en", customer_id=None):
        dialog = CustomerDialog(translator(language, str(ROOT / "utils")), self.controller, customer_id)
        self.widgets.append(dialog)
        dialog.show()
        self.app.processEvents()
        return dialog

    def test_phone_migration_preserves_legacy_data_and_is_repeatable(self):
        legacy_path = Path(self.temp_dir.name) / "legacy.db"
        with closing(sqlite3.connect(legacy_path)) as connection, connection:
            connection.execute("""CREATE TABLE customers (
                customer_id INTEGER PRIMARY KEY AUTOINCREMENT, first_name TEXT NOT NULL,
                last_name TEXT NOT NULL, email TEXT UNIQUE, street TEXT NOT NULL,
                postal_code TEXT NOT NULL, city TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")
            connection.execute("INSERT INTO customers VALUES (7, 'Legacy', 'Customer', NULL, 'Original street', 'Code', 'City', '2026-01-01 12:00:00')")
            before = connection.execute("SELECT * FROM customers").fetchall()
        DatabaseManager(str(legacy_path))
        with closing(sqlite3.connect(legacy_path)) as connection:
            after = connection.execute("SELECT customer_id, first_name, last_name, email, street, postal_code, city, created_at, phone FROM customers").fetchall()
            columns = [row[1] for row in connection.execute("PRAGMA table_info(customers)")]
        self.assertEqual(columns.count("phone"), 1)
        self.assertEqual([row[:-1] for row in after], before)
        self.assertIsNone(after[0][-1])
        snapshot = self.database_dump(legacy_path)
        DatabaseManager(str(legacy_path))
        self.assertEqual(self.database_dump(legacy_path), snapshot)

    def test_required_fields_and_email_structure_are_validated_without_writes(self):
        before = self.database_dump()
        for field in self.controller.REQUIRED_FIELDS:
            with self.subTest(field=field), self.assertRaises(CustomerValidationError) as error:
                self.controller.validate(dict(VALID, **{field: "   "}))
            self.assertEqual((error.exception.code, error.exception.field), ("required", field))
        for email in ("invalid", "a@", "@example.test", "a b@example.test", "a..b@example.test", "a@example..test", "a@-example.test"):
            with self.subTest(email=email), self.assertRaises(CustomerValidationError) as error:
                self.controller.validate(dict(VALID, email=email))
            self.assertEqual(error.exception.code, "invalid_email")
        self.assertEqual(self.database_dump(), before)

    def test_optional_contact_values_are_absent_without_national_format_rules(self):
        values = self.controller.validate(dict(VALID, email="  ", phone=""))
        self.assertIsNone(values["email"])
        self.assertIsNone(values["phone"])
        values = self.controller.validate(dict(VALID, phone="ext. 42 / +44 (0) 20 1234 5678", postal_code="SW1A 1AA"))
        self.assertEqual(values["phone"], "ext. 42 / +44 (0) 20 1234 5678")
        self.assertEqual(values["postal_code"], "SW1A 1AA")

    def test_cancelled_forms_preserve_records_in_both_languages_and_every_theme(self):
        customer_id = self.insert_fixture_customer()
        before = self.database_dump()
        for language in ("en", "pl"):
            for theme in ("light", "dark", "modern"):
                with self.subTest(language=language, theme=theme):
                    ThemeManager.apply_theme(self.app, theme, "medium")
                    dialog = self.open_dialog(language, customer_id)
                    self.assertEqual(dialog.windowTitle(), dialog.t("cust_edit"))
                    for field, expected in VALID.items():
                        self.assertEqual(dialog.fields[field].text(), expected)
                    dialog.fields["phone"].setText("unsaved")
                    self.assertEqual(dialog.fields["phone"].palette().color(QPalette.Text).name(),
                                     ThemeManager.get_palette(theme)["text_main"])
                    QTest.mouseClick(dialog.buttons.button(QDialogButtonBox.Cancel), Qt.LeftButton)
                    self.assertIsNone(dialog.saved_customer_id)
        self.assertEqual(self.database_dump(), before)

    def test_customers_navigation_uses_configured_database_and_stable_row_identity(self):
        customer_id = self.insert_fixture_customer()
        config = {"paths": {"database": str(self.db_path)}, "localization": {"language": "en"}}
        Path("config.json").write_text(json.dumps(config), encoding="utf-8")
        window = MainWindow(config, self.translator)
        self.widgets.append(window)
        window.show()
        window.btn_customers.click()
        self.assertIs(window.stacked_widget.currentWidget(), window.view_customers)
        self.assertEqual(window.customer_ctrl.db_path, str(self.db_path))
        view = window.view_customers
        self.assertEqual(view.table.rowCount(), 1)
        view.table.selectRow(0)
        self.assertEqual(view.selected_customer_id(), customer_id)
        self.assertTrue(view.edit_button.isEnabled())
        self.assertEqual(view.table.item(0, 0).text(), str(customer_id))
        self.assertEqual(view.table.item(0, 4).text(), VALID["phone"])
        self.assertFalse(Path("warehouse.db").exists())

    def test_add_edit_reopen_preserves_identity_and_optional_contacts(self):
        customer_id = self.controller.save_customer(VALID)
        reopened = CustomerController(str(self.db_path))
        self.assertEqual(dict(reopened.get_customer(customer_id)), dict(VALID, customer_id=customer_id, is_active=1))
        edited = dict(VALID, first_name="Anne", phone="+44 20 1234 5678")
        self.assertEqual(reopened.save_customer(edited, customer_id), customer_id)
        self.assertEqual(dict(self.controller.get_customer(customer_id)), dict(edited, customer_id=customer_id, is_active=1))
        for _ in range(2):
            blank_id = self.controller.save_customer(dict(VALID, email="  ", phone=""))
            self.assertIsNone(self.controller.get_customer(blank_id)["email"])
            self.assertIsNone(self.controller.get_customer(blank_id)["phone"])
        self.assertEqual(len(self.controller.get_customers()), 3)

    def test_email_uniqueness_ignores_case_and_allows_editing_the_same_record(self):
        for original, duplicate in (("AnNa@Example.Test", "anna@EXAMPLE.test"),
                                    ("Test@ŁÓDŹ.test", "test@łódź.TEST")):
            with self.subTest(email=original):
                customer_id = self.controller.save_customer(dict(VALID, email=original))
                before = self.database_dump()
                with self.assertRaises(CustomerValidationError) as error:
                    self.controller.save_customer(dict(VALID, email=duplicate))
                self.assertEqual(error.exception.code, "duplicate_email")
                self.assertEqual(self.database_dump(), before)
                self.controller.save_customer(dict(VALID, email=duplicate, phone="Changed"), customer_id)
                self.assertEqual(self.controller.get_customer(customer_id)["email"], duplicate)

    def test_competing_saves_cannot_create_case_variant_duplicates(self):
        barrier = Barrier(2)

        def attempt(email):
            controller = CustomerController(str(self.db_path))
            barrier.wait(timeout=5)
            try:
                return "saved", controller.save_customer(dict(VALID, email=email))
            except CustomerValidationError as error:
                return error.code, None

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(attempt, "Shared@Example.test")
            second = executor.submit(attempt, "shared@example.TEST")
            results = [first.result(timeout=10), second.result(timeout=10)]
        self.assertEqual(sorted(result[0] for result in results), ["duplicate_email", "saved"])
        self.assertEqual(len(self.controller.get_customers()), 1)

    def test_legacy_case_collisions_are_reported_without_automatic_changes(self):
        first_id = self.insert_fixture_customer()
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            second_id = connection.execute(
                "INSERT INTO customers (first_name, last_name, street, postal_code, city, email) "
                "VALUES ('Legacy', 'Duplicate', 'Street', 'Code', 'City', 'ANNA@EXAMPLE.TEST')",
            ).lastrowid
        before = self.database_dump()
        DatabaseManager(str(self.db_path))
        self.assertEqual(self.controller.get_email_conflicts(), [[first_id, second_id]])
        view = CustomersView(self.translator, self.controller)
        self.widgets.append(view)
        self.assertIn(f"{first_id}, {second_id}", view.conflict_message.text())
        with self.assertRaises(CustomerValidationError) as error:
            self.controller.save_customer(dict(VALID, phone="Unsaved"), first_id)
        self.assertEqual(error.exception.code, "duplicate_email")
        self.assertEqual(self.database_dump(), before)

    def test_master_data_edits_preserve_historical_order_invoice_and_item_values(self):
        customer_id = self.controller.save_customer(VALID)
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute("INSERT INTO products (product_id, sku, name_pl, name_en, price) VALUES (1, 'HISTORY', 'Produkt', 'Product', 99)")
            connection.execute("INSERT INTO orders (order_id, customer_id, delivery_name, delivery_street, delivery_city, total_amount) VALUES (1, ?, 'Original recipient', 'Original street', 'Original city', 20)", (customer_id,))
            connection.execute("INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (1, 1, 2, 10)")
            connection.execute("INSERT INTO invoices (order_id, invoice_number, billing_name, billing_street, billing_city) VALUES (1, 'INV-1', 'Original payer', 'Billing street', 'Billing city')")
            tables = ("orders", "order_items", "invoices")
            before = {table: connection.execute(f"SELECT * FROM {table}").fetchall() for table in tables}
        self.controller.save_customer(dict(VALID, first_name="New name", street="New street", city="New city"), customer_id)
        with closing(sqlite3.connect(self.db_path)) as connection:
            after = {table: connection.execute(f"SELECT * FROM {table}").fetchall() for table in tables}
        self.assertEqual(after, before)

    def test_forms_save_once_and_show_translated_validation_errors(self):
        for language in ("en", "pl"):
            with self.subTest(language=language):
                dialog = self.open_dialog(language)
                values = dict(VALID, email=f"{language}@example.test")
                for field, value in values.items():
                    dialog.fields[field].setText(value)
                QTest.mouseClick(dialog.buttons.button(QDialogButtonBox.Save), Qt.LeftButton)
                self.assertEqual(dialog.result(), QDialog.Accepted)
                customer_id = dialog.saved_customer_id
                count = len(self.controller.get_customers())
                dialog.save()
                self.assertEqual(len(self.controller.get_customers()), count)
                edited = self.open_dialog(language, customer_id)
                before = self.database_dump()
                edited.fields["first_name"].clear()
                QTest.mouseClick(edited.buttons.button(QDialogButtonBox.Save), Qt.LeftButton)
                self.assertEqual(edited.error_label.text(), edited.t("cust_error_required").format(field=edited.t("cust_first_name")))
                self.assertEqual(edited.result(), QDialog.Rejected)
                self.assertEqual(self.database_dump(), before)
                edited.fields["first_name"].setText(values["first_name"])
                edited.fields["phone"].setText("Updated phone")
                QTest.mouseClick(edited.buttons.button(QDialogButtonBox.Save), Qt.LeftButton)
                self.assertEqual(edited.saved_customer_id, customer_id)
                self.assertEqual(self.controller.get_customer(customer_id)["phone"], "Updated phone")

    def test_failed_storage_save_leaves_the_form_open_and_data_unchanged(self):
        customer_id = self.insert_fixture_customer()
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute("CREATE TRIGGER reject_customer_update BEFORE UPDATE ON customers BEGIN SELECT RAISE(ABORT, 'test storage rejection'); END")
        before = self.database_dump()
        dialog = self.open_dialog(customer_id=customer_id)
        dialog.fields["phone"].setText("Unsaved")
        QTest.mouseClick(dialog.buttons.button(QDialogButtonBox.Save), Qt.LeftButton)
        self.assertEqual(dialog.result(), QDialog.Rejected)
        self.assertEqual(dialog.error_label.text(), dialog.t("cust_error_storage"))
        self.assertEqual(self.database_dump(), before)


if __name__ == "__main__":
    unittest.main()
