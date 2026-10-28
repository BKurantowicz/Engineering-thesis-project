"""Integration regressions for real controller rows rendered by the Orders UI."""

from contextlib import closing
from datetime import datetime, timedelta
import gc
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from controllers.order_controller import OrderController
from main import MainWindow, load_config
from models.database import DatabaseManager
from utils.translations import translator
from views.orders.orders_view import OrdersView


ROOT = Path(__file__).resolve().parents[1]


class OrdersViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        previous_directory = Path.cwd()
        os.chdir(self.temp_dir.name)
        self.addCleanup(os.chdir, previous_directory)
        # Existing controller context managers commit transactions; collect their
        # unreachable SQLite handles before Windows removes the fixture directory.
        self.addCleanup(gc.collect)
        self.widgets = []
        self.addCleanup(self.close_widgets)
        self.database_path = Path(self.temp_dir.name) / "warehouse.db"
        DatabaseManager(str(self.database_path))
        self.config = {
            "localization": {"language": "en", "date_format": "YYYY-MM-DD"},
            "appearance": {"theme": "dark", "font_size": "medium"},
            "paths": {"database": "warehouse.db"},
        }
        Path("config.json").write_text(json.dumps(self.config), encoding="utf-8")
        self.translator = translator("en", str(ROOT / "utils"))
        now = datetime.now()
        self.dates = [(now - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S") for days in (1, 20, 400)]
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.executemany(
                "INSERT INTO customers (customer_id, first_name, last_name, street, postal_code, city) VALUES (?, ?, ?, ?, ?, ?)",
                [(1, "Alice", "First", "First Street", "00-001", "Warsaw"),
                 (2, "Bob", "Second", "Second Street", "90-001", "Lodz")],
            )
            connection.executemany(
                "INSERT INTO products (product_id, sku, name_pl, name_en, price, weight) VALUES (?, ?, ?, ?, ?, ?)",
                [(1, "ITEM-A", "Produkt A", "Product A", 123, 1.25),
                 (2, "ITEM-B", "Produkt B", "Product B", 123, 2.5)],
            )
            connection.execute("INSERT INTO locations (location_id, location_code, max_weight, max_volume) VALUES (1, 'A-01', 500, 1)")
            connection.execute("INSERT INTO inventory VALUES (1, 1, 10)")
            connection.executemany(
                """INSERT INTO orders (order_id, customer_id, order_date, status_code, total_amount, payment_method_id,
                    delivery_name, delivery_second_name, delivery_street, delivery_postal_code, delivery_city)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [(101, 1, self.dates[0], "NEW", 123, None, "Recipient A", "A", "A Street", "00-001", "Warsaw"),
                 (102, 2, self.dates[1], "SHIPPED", 246, 1, "Recipient B", "B", "B Street", "90-001", "Lodz"),
                 (103, 1, self.dates[2], "IN_PROGRESS", 73.8, None, None, None, None, None, None)],
            )
            connection.executemany(
                "INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (?, ?, ?, ?)",
                [(101, 1, 1, 123), (102, 2, 2, 123)],
            )
            connection.execute(
                """INSERT INTO order_shipments (order_id, shipping_type_id, package_code, tracking_number, final_shipping_cost)
                    VALUES (102, 1, 'INPOST_A', 'TRACK-102', 14.99)""",
            )

    def close_widgets(self):
        for widget in self.widgets:
            widget.close()
            widget.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def open_view(self):
        view = OrdersView(self.translator)
        self.widgets.append(view)
        view.resize(1200, 700)
        view.show()
        self.app.processEvents()
        return view

    def rows(self, view):
        return [view.scroll_layout.itemAt(index).widget() for index in range(view.scroll_layout.count())]

    def database_dump(self):
        with closing(sqlite3.connect(self.database_path)) as connection:
            return list(connection.iterdump())

    def test_real_named_rows_render_correct_values_and_missing_join_defaults(self):
        records = OrderController(str(self.database_path)).get_orders()
        self.assertEqual(len(records), 3)
        self.assertEqual(len(records[0].keys()), 14)
        view = self.open_view()
        expected = [
            ["ORD-00101", self.dates[0][:16], "-", "NEW", "100.00", "123.00", "-", "-", "0.00", "Alice First"],
            ["ORD-00102", self.dates[1][:16], self.dates[1][:16], "SHIPPED", "200.00", "246.00", "Przelew", "INPOST_A", "14.99", "Bob Second"],
            ["ORD-00103", self.dates[2][:16], "-", "IN_PROGRESS", "60.00", "73.80", "-", "-", "0.00", "Alice First"],
        ]
        actual = [[row.summary_layout.itemAt(i).widget().text() for i in range(row.summary_layout.count())] for row in self.rows(view)]
        self.assertEqual(actual, expected)

    def test_empty_order_table_loads_and_reloads(self):
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.execute("DELETE FROM order_items")
            connection.execute("DELETE FROM order_shipments")
            connection.execute("DELETE FROM orders")
        view = self.open_view()
        self.assertEqual(view.scroll_layout.count(), 0)
        view.load_orders()
        self.assertEqual(view.scroll_layout.count(), 0)

    def test_expanding_details_uses_the_correct_order_items_without_writes(self):
        before = self.database_dump()
        view = self.open_view()
        rows = self.rows(view)
        for row, sku, quantity, total, weight in (
            (rows[0], "ITEM-A", "1 pcs", "123.00 PLN", "1.25 kg"),
            (rows[1], "ITEM-B", "2 pcs", "246.00 PLN", "5.00 kg"),
        ):
            with self.subTest(order=row.order_id_str):
                QTest.mouseClick(row.summary_row, Qt.LeftButton)
                self.assertTrue(row.summary_row.is_expanded)
                self.assertFalse(row.details_panel.isHidden())
                table = row.products_table
                self.assertEqual(table.rowCount(), 1)
                self.assertEqual(table.item(0, 0).text(), sku)
                self.assertEqual(table.item(0, 2).text(), quantity)
                self.assertEqual(table.item(0, 4).text(), total)
                self.assertEqual(table.item(0, 5).text(), weight)
                QTest.mouseClick(row.summary_row, Qt.LeftButton)
                self.assertTrue(row.details_panel.isHidden())
        self.assertEqual(rows[2].products_table.rowCount(), 0)
        self.assertEqual(self.database_dump(), before)

    def test_existing_date_and_limit_controls_reload_without_duplicates(self):
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.executemany(
                "INSERT INTO orders (order_id, customer_id, order_date, status_code, total_amount) VALUES (?, 1, ?, 'NEW', 1.23)",
                [(number, self.dates[0]) for number in range(200, 255)],
            )
        before = self.database_dump()
        view = self.open_view()
        self.assertEqual(view.scroll_layout.count(), 50)
        for limit, count in ((100, 58), (0, 58), (50, 50), (0, 58)):
            view.limit_filter.setCurrentIndex(view.limit_filter.findData(limit))
            self.assertEqual(view.scroll_layout.count(), count)
            self.assertEqual(len({row.order_id_str for row in self.rows(view)}), count)
        view.date_filter.setCurrentIndex(view.date_filter.findData("last_7"))
        self.assertEqual(view.scroll_layout.count(), 56)
        view.date_filter.setCurrentIndex(view.date_filter.findData(""))
        self.assertEqual(view.scroll_layout.count(), 58)
        view.load_orders()
        self.assertEqual(view.scroll_layout.count(), 58)
        self.assertEqual(self.database_dump(), before)

    def test_main_window_starts_with_populated_database_and_preserves_records(self):
        before = self.database_dump()
        window = MainWindow(load_config(), self.translator)
        self.widgets.append(window)
        window.show()
        self.app.processEvents()
        window.btn_sub_overview.click()
        self.assertIs(window.stacked_widget.currentWidget(), window.view_orders)
        self.assertEqual(window.view_orders.scroll_layout.count(), 3)
        window.view_orders.load_orders()
        self.assertEqual(window.view_orders.scroll_layout.count(), 3)
        QTest.mouseClick(self.rows(window.view_orders)[0].summary_row, Qt.LeftButton)
        self.assertTrue(self.rows(window.view_orders)[0].summary_row.is_expanded)
        self.assertEqual(self.database_dump(), before)


if __name__ == "__main__":
    unittest.main()
