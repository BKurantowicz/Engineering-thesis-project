"""Database selection integration coverage using isolated, distinguishable files."""

from contextlib import closing
import gc
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from main import MainWindow, load_config
from models.database import DatabaseManager
from utils.translations import translator


ROOT = Path(__file__).resolve().parents[1]


class DatabasePathTests(unittest.TestCase):
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
        self.windows = []
        self.addCleanup(self.close_windows)
        self.translator = translator("en", str(ROOT / "utils"))

    def close_windows(self):
        for window in self.windows:
            window.close()
            window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def create_database(self, path, marker, first_id, count=1):
        DatabaseManager(str(path))
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute(
                "INSERT INTO customers (customer_id, first_name, last_name, street, postal_code, city) VALUES (1, ?, 'Customer', 'Street', '00-001', 'City')",
                (marker,),
            )
            connection.execute(
                "INSERT INTO products (product_id, sku, name_pl, name_en, price, weight) VALUES (1, ?, ?, ?, 10, 1)",
                (marker, marker, marker),
            )
            connection.executemany(
                "INSERT INTO orders (order_id, customer_id, status_code, total_amount) VALUES (?, 1, 'NEW', 20)",
                [(number,) for number in range(first_id, first_id + count)],
            )
            connection.execute(
                "INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (?, 1, 2, 10)",
                (first_id,),
            )

    def select_database(self, path):
        Path("config.json").write_text(json.dumps({
            "localization": {"language": "en"},
            "appearance": {"theme": "dark", "font_size": "medium"},
            "paths": {"database": str(path)},
        }), encoding="utf-8")

    def open_window(self):
        window = MainWindow(load_config(), self.translator)
        self.windows.append(window)
        return window

    def order_ids(self, window):
        return {row["order_id"] for row in window.view_orders.controller.get_orders(limit=0)}

    def assert_same_path(self, window, path):
        self.assertEqual(window.db.db_path, str(path))
        self.assertEqual(window.dashboard_ctrl.db_path, str(path))
        self.assertEqual(window.view_orders.controller.db_path, str(path))

    def test_nondefault_database_starts_without_creating_default_file(self):
        self.create_database("configured.db", "SELECTED", 101, count=2)
        self.select_database("configured.db")
        self.assertFalse(Path("warehouse.db").exists())
        window = self.open_window()
        self.assert_same_path(window, "configured.db")
        self.assertEqual(self.order_ids(window), {101, 102})
        self.assertEqual(window.dashboard_ctrl.get_order_status_counts()["NEW"], 2)
        window.view_orders.load_orders()
        self.assertEqual(window.view_orders.scroll_layout.count(), 2)
        self.assertFalse(Path("warehouse.db").exists())

    def test_reads_details_reloads_and_writes_use_selected_file_only(self):
        self.create_database("configured.db", "SELECTED", 101, count=2)
        self.create_database("warehouse.db", "UNSELECTED", 901)
        unselected_before = Path("warehouse.db").read_bytes()
        self.select_database("configured.db")
        window = self.open_window()
        self.assertEqual(self.order_ids(window), {101, 102})
        self.assertEqual(window.dashboard_ctrl.get_order_status_counts()["NEW"], 2)
        controller = window.view_orders.controller
        self.assertEqual(controller.get_order_items(101)[0]["sku"], "SELECTED")
        new_id = controller.add_order(1, 1, None, 30, {"name": "Selected recipient", "city": "Warsaw"})
        window.view_orders.load_orders()
        self.assertEqual(self.order_ids(window), {101, 102, new_id})
        self.assertEqual(window.view_orders.scroll_layout.count(), 3)
        self.assertEqual(window.dashboard_ctrl.get_order_status_counts()["NEW"], 3)
        with closing(sqlite3.connect("configured.db")) as connection:
            self.assertEqual(connection.execute("SELECT delivery_name FROM orders WHERE order_id = ?", (new_id,)).fetchone()[0], "Selected recipient")
        self.assertEqual(Path("warehouse.db").read_bytes(), unselected_before)

    def test_relative_absolute_and_default_paths_keep_existing_resolution(self):
        paths = ["data/relative.db", str(Path(self.temp_dir.name) / "absolute.db"), "warehouse.db"]
        for index, path in enumerate(paths):
            with self.subTest(path=path):
                order_id = 100 + index
                self.create_database(path, f"SOURCE-{index}", order_id)
                self.select_database(path)
                window = self.open_window()
                self.assert_same_path(window, path)
                self.assertEqual(Path(window.db_path).resolve(), Path(path).resolve())
                self.assertEqual(self.order_ids(window), {order_id})
                if path != "warehouse.db":
                    self.assertFalse(Path("warehouse.db").exists())

    def test_saved_path_change_is_used_by_all_consumers_after_restart(self):
        self.create_database("first.db", "FIRST", 101)
        self.create_database("second.db", "SECOND", 202, count=2)
        self.select_database("first.db")
        first_window = self.open_window()
        self.assertEqual(self.order_ids(first_window), {101})
        updated = first_window.settings_ctrl.get_config()
        updated["paths"]["database"] = "second.db"
        self.assertTrue(first_window.settings_ctrl.save_config(updated))
        self.assert_same_path(first_window, "first.db")
        first_window.close()

        restarted = self.open_window()
        self.assert_same_path(restarted, "second.db")
        self.assertEqual(self.order_ids(restarted), {202, 203})
        self.assertEqual(restarted.dashboard_ctrl.get_order_status_counts()["NEW"], 2)
        self.assertFalse(Path("warehouse.db").exists())


if __name__ == "__main__":
    unittest.main()
