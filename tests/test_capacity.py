"""Physical occupancy calculations and translated dashboard refresh regressions."""

from contextlib import closing
from decimal import Decimal
import gc
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from controllers.capacity_controller import CapacityController
from controllers.dashboard_controller import DashboardController
from models.database import DatabaseManager
from utils.theme_manager import ThemeManager
from utils.translations import translator
from views.dashboard.dashboard_view import DashboardView


ROOT = Path(__file__).resolve().parents[1]


class CapacityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.addCleanup(gc.collect)
        self.db_path = str(Path(self.temp_dir.name) / "capacity.db")
        DatabaseManager(self.db_path)
        self.controller = CapacityController(self.db_path)
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

    def fixture(self):
        self.sql("INSERT INTO locations (location_id, location_code, max_weight, max_volume) VALUES (1, 'A-01', 500, 1), (2, 'B-02', 750, 1.5)")
        self.sql("INSERT INTO products (product_id, sku, name_pl, name_en, price, weight, length, width, height) VALUES (1, 'P1', 'Produkt', 'Product', 12, 2.5, 20, 25, 40)")
        self.sql("INSERT INTO inventory VALUES (1, 1, 20), (1, 2, 10)")

    def test_unit_conversion_and_weighted_warehouse_totals(self):
        self.fixture()
        before = Path(self.db_path).read_bytes()
        data = self.controller.get_capacity()
        self.assertEqual(data["weight"]["used"], Decimal("75"))
        self.assertEqual(data["weight"]["capacity"], Decimal("1250"))
        self.assertEqual(data["weight"]["percentage"], Decimal("6"))
        self.assertEqual(data["volume"]["used"], Decimal("0.6"))
        self.assertEqual(data["volume"]["percentage"], Decimal("24"))
        self.assertEqual(data["racks"][0]["weight"]["percentage"], Decimal("10"))
        self.assertEqual(data["racks"][0]["volume"]["percentage"], Decimal("40"))
        self.assertNotEqual(data["volume"]["percentage"], sum(rack["volume"]["percentage"] for rack in data["racks"]) / 2)
        self.assertEqual(Path(self.db_path).read_bytes(), before)

    def test_virtual_locations_exclude_stock_and_limits_even_with_invalid_measurements(self):
        self.fixture()
        expected = self.controller.get_capacity()
        self.sql("INSERT INTO locations (location_id, location_code, max_weight, max_volume, is_virtual) VALUES (3, ' BrAkI ', 9999, 9999, 0), (4, 'Reporting', 9999, 9999, 1)")
        self.sql("INSERT INTO products (product_id, sku, name_pl, name_en, price) VALUES (2, 'Missing', 'Brak', 'Missing', 1)")
        self.sql("INSERT INTO inventory VALUES (2, 3, 900), (2, 4, 800)")
        self.assertEqual(self.controller.get_capacity(), expected)

    def test_legacy_location_migration_preserves_values_and_classifies_braki(self):
        legacy = str(Path(self.temp_dir.name) / "legacy.db")
        with closing(sqlite3.connect(legacy)) as connection, connection:
            connection.execute("CREATE TABLE locations (location_id INTEGER PRIMARY KEY, location_code TEXT UNIQUE NOT NULL, max_weight REAL NOT NULL, max_volume REAL NOT NULL)")
            connection.execute("INSERT INTO locations VALUES (7, 'A-01', 500, 1), (8, ' BrAkI ', 1, 1)")
        DatabaseManager(legacy)
        DatabaseManager(legacy)
        with closing(sqlite3.connect(legacy)) as connection:
            self.assertEqual(connection.execute("SELECT * FROM locations ORDER BY location_id").fetchall(), [(7, "A-01", 500, 1, 0), (8, " BrAkI ", 1, 1, 1)])
            self.assertEqual([row[1] for row in connection.execute("PRAGMA table_info(locations)")].count("is_virtual"), 1)

    def test_empty_valid_racks_are_zero_but_no_physical_racks_is_unavailable(self):
        self.assertEqual(self.controller.get_capacity()["weight"]["reasons"], ["no_physical_racks"])
        self.fixture()
        self.sql("UPDATE inventory SET quantity = 0")
        self.sql("UPDATE products SET weight = 0, length = 0, width = 0, height = 0")
        data = self.controller.get_capacity()
        for metric in self.controller.METRICS:
            self.assertEqual(data[metric]["percentage"], 0)
            self.assertEqual(data[metric]["reasons"], [])

    def test_invalid_measurements_and_limits_are_independent(self):
        self.fixture()
        for field in ("weight", "length", "width", "height"):
            for invalid in (0, -1, "invalid", float("inf")):
                with self.subTest(field=field, invalid=invalid):
                    self.sql("UPDATE products SET weight = 2.5, length = 20, width = 25, height = 40")
                    self.sql(f"UPDATE products SET {field} = ?", (invalid,))
                    data = self.controller.get_capacity()
                    affected = "weight" if field == "weight" else "volume"
                    other = "volume" if affected == "weight" else "weight"
                    self.assertIsNone(data[affected]["percentage"])
                    self.assertIn("invalid_measurements", data[affected]["reasons"])
                    self.assertIsNotNone(data[other]["percentage"])
        self.sql("UPDATE products SET weight = 2.5, length = 20, width = 25, height = 40")
        self.sql("UPDATE locations SET max_weight = 0 WHERE location_id = 1")
        data = self.controller.get_capacity()
        self.assertIsNone(data["weight"]["percentage"])
        self.assertIn("invalid_limits", data["weight"]["reasons"])
        self.assertEqual(data["volume"]["percentage"], 24)

    def test_invalid_quantity_and_orphan_references_cannot_report_free_capacity(self):
        self.fixture()
        for invalid in (-1, 1.5, "bad"):
            self.sql("UPDATE inventory SET quantity = ? WHERE location_id = 1", (invalid,))
            for metric in self.controller.METRICS:
                self.assertIn("invalid_quantity", self.controller.get_capacity()[metric]["reasons"])
        self.sql("UPDATE inventory SET quantity = 20 WHERE location_id = 1")
        self.sql("INSERT INTO inventory VALUES (1, 99, 1)")
        self.assertIn("unclassified_stock", self.controller.get_capacity()["weight"]["reasons"])
        self.sql("DELETE FROM inventory WHERE location_id = 99")
        # Model a pre-existing orphan without bypassing the product deletion guard.
        self.sql("UPDATE inventory SET product_id = 999")
        self.assertIn("invalid_measurements", self.controller.get_capacity()["volume"]["reasons"])

    def test_order_allocation_does_not_reduce_occupancy_but_physical_removal_does(self):
        self.fixture()
        before = self.controller.get_capacity()
        self.sql("INSERT INTO orders (order_id, status_code) VALUES (1, 'IN_PROGRESS')")
        self.sql("INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (1, 1, 5, 12)")
        self.sql("INSERT INTO pick_lists (pick_list_id, status) VALUES (1, 'IN_PROGRESS')")
        self.sql("INSERT INTO pick_list_orders VALUES (1, 1)")
        self.assertEqual(self.controller.get_capacity(), before)
        self.sql("UPDATE inventory SET quantity = quantity - 5 WHERE location_id = 1")
        after = self.controller.get_capacity()
        self.assertEqual(after["weight"]["used"], Decimal("62.5"))
        self.assertEqual(after["volume"]["used"], Decimal("0.5"))

    def test_existing_over_capacity_data_is_reported_without_clamping_or_mutation(self):
        self.fixture()
        self.sql("UPDATE inventory SET quantity = 60 WHERE location_id = 1")
        data = self.controller.get_capacity()
        self.assertEqual(data["racks"][0]["volume"]["percentage"], 120)
        self.assertEqual(self.sql("SELECT quantity FROM inventory WHERE location_id = 1"), [(60,)])

    def test_database_read_failure_is_unavailable_not_empty(self):
        self.sql("DROP TABLE inventory")
        for name in self.controller.METRICS:
            metric = self.controller.get_capacity()[name]
            self.assertIsNone(metric["percentage"])
            self.assertEqual(metric["reasons"], ["database_error"])

    def test_dashboard_scope_refresh_and_unavailable_state_in_both_languages_and_all_themes(self):
        self.fixture()
        self.sql("INSERT INTO locations (location_code, max_weight, max_volume, is_virtual) VALUES ('braki', 1, 1, 1)")
        for language in ("en", "pl"):
            trans = translator(language, str(ROOT / "utils"))
            view = DashboardView(trans, DashboardController(self.db_path))
            self.widgets.append(view)
            view.resize(1100, 720)
            view.show()
            for theme in ("light", "dark", "modern"):
                with self.subTest(language=language, theme=theme):
                    self.sql("UPDATE products SET weight = 2.5")
                    self.sql("UPDATE locations SET max_volume = 1 WHERE location_id = 1")
                    self.sql("UPDATE inventory SET quantity = 20 WHERE location_id = 1")
                    ThemeManager.apply_theme(self.app, theme, "medium")
                    view.load_real_data()
                    view.capacity_scope.setCurrentIndex(0)
                    self.app.processEvents()
                    self.assertGreaterEqual(view.bottom_layout.itemAt(1).widget().width(), 350)
                    self.assertEqual(view.capacity_scope.count(), 3)
                    self.assertIn("(24.0%)", view.capacity_labels["volume"].text())
                    view.capacity_scope.setCurrentIndex(view.capacity_scope.findData(1))
                    self.assertIn("(40.0%)", view.capacity_labels["volume"].text())
                    view.time_filter.setCurrentIndex(2)
                    self.sql("UPDATE inventory SET quantity = 10 WHERE location_id = 1")
                    self.sql("UPDATE locations SET max_volume = 2 WHERE location_id = 1")
                    view.capacity_reload.click()
                    self.assertEqual(view.capacity_scope.currentData(), 1)
                    self.assertEqual(view.time_filter.currentIndex(), 2)
                    self.assertIn("(10.0%)", view.capacity_labels["volume"].text())
                    self.sql("UPDATE products SET weight = 0")
                    view.capacity_reload.click()
                    self.assertIn(trans.t("cap_unavailable"), view.capacity_labels["weight"].text())
                    self.assertTrue(view.capacity_bars["weight"].isHidden())
                    self.assertFalse(view.capacity_bars["volume"].isHidden())
                    self.assertEqual(view.capacity_labels["weight"].toolTip(), trans.t("cap_invalid_measurements"))
                    self.assertEqual(view.capacity_labels["weight"].palette().color(QPalette.WindowText), QColor(ThemeManager.get_palette(theme)["text_main"]))
                    self.assertFalse(hasattr(view, "capacity_chart"))
                    self.assertEqual(view.capacity_panel.styleSheet(), "")


if __name__ == "__main__":
    unittest.main()
