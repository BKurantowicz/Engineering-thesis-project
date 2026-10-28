"""Runtime themes exercised through real views, charts, and isolated storage."""

from contextlib import closing
import gc
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QFrame, QLabel, QLineEdit

from main import MainWindow
from models.database import DatabaseManager
from utils.theme_manager import ThemeManager
from utils.translations import translator
from views.dashboard.dashboard_view import DashboardView


ROOT = Path(__file__).resolve().parents[1]


class RuntimeThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.previous_directory = Path.cwd()
        os.chdir(self.temp_dir.name)
        self.addCleanup(os.chdir, self.previous_directory)
        self.addCleanup(gc.collect)
        self.widgets = []
        self.addCleanup(self.close_widgets)
        self.addCleanup(self.app.setStyleSheet, self.app.styleSheet())
        for name in ("theme_name", "font_size_name"):
            self.addCleanup(self.app.setProperty, name, self.app.property(name))
        self.config = {
            "paths": {"database": "theme-test.db"},
            "localization": {"language": "en", "date_format": "YYYY-MM-DD"},
            "appearance": {"theme": "dark", "font_size": "medium"},
        }
        Path("config.json").write_text(json.dumps(self.config), encoding="utf-8")
        DatabaseManager("theme-test.db")
        with closing(sqlite3.connect("theme-test.db")) as connection, connection:
            connection.execute("INSERT INTO customers (customer_id, first_name, last_name, street, postal_code, city) VALUES (1, 'Alice', 'Test', 'Street', '00-001', 'City')")
            connection.execute("INSERT INTO products (product_id, sku, name_pl, name_en, price, weight) VALUES (1, 'THEME-1', 'Produkt', 'Product', 12.30, 1)")
            connection.execute("INSERT INTO locations VALUES (1, 'A-01', 500, 1)")
            connection.execute("INSERT INTO inventory VALUES (1, 1, 3000)")
            for number, status in enumerate(("NEW", "IN_PROGRESS", "PACKED", "SHIPPED"), 1):
                connection.execute("INSERT INTO orders (order_id, customer_id, status_code, total_amount) VALUES (?, 1, ?, 12.30)", (number, status))
                connection.execute("INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (?, 1, 1, 12.30)", (number,))
        dialog = patch("PySide6.QtWidgets.QMessageBox.information")
        dialog.start()
        self.addCleanup(dialog.stop)
        ThemeManager.apply_theme(self.app, "dark", "medium")
        self.window = self.open_window("en")

    def close_widgets(self):
        for widget in self.widgets:
            widget.close()
            widget.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def open_window(self, language):
        window = MainWindow(self.config, translator(language, str(ROOT / "utils")))
        self.widgets.append(window)
        window.show()
        self.app.processEvents()
        return window

    def save_theme(self, window, theme):
        window.view_settings.cb_theme.setCurrentText(theme)
        window.view_settings.save_btn.click()
        self.app.processEvents()
        self.assertEqual(json.loads(Path("config.json").read_text())["appearance"]["theme"], theme)
        return ThemeManager.get_palette(theme)

    def assert_color(self, actual, expected):
        self.assertEqual(actual.name(), QColor(expected).name())

    def assert_chart_colors(self, dashboard, palette):
        for chart in (dashboard.trend_chart, dashboard.capacity_chart, dashboard.status_chart):
            self.assert_color(chart.backgroundBrush().color(), palette["bg_card"])
            self.assert_color(chart.titleBrush().color(), palette["text_main"])
            self.assert_color(chart.legend().labelColor(), palette["text_main"])
            for axis in chart.axes():
                self.assert_color(axis.labelsColor(), palette["text_main"])
                self.assert_color(axis.gridLineColor(), palette["border"])
        for series in dashboard.trend_chart.series():
            self.assert_color(series.pointLabelsColor(), palette["text_main"])
        for bar, key in zip(dashboard.status_chart.series()[0].barSets(),
                            ("chart_new", "chart_progress", "chart_packed", "chart_shipped")):
            self.assert_color(bar.color(), palette[key])
            self.assert_color(bar.labelColor(), palette["text_main"])
        for section in dashboard.capacity_chart.series()[0].slices():
            self.assert_color(section.labelColor(), palette["text_main"])

    def test_saving_rethemes_existing_views_and_charts_in_both_languages(self):
        for window in (self.window, self.open_window("pl")):
            dashboard = window.view_dashboard
            charts = (dashboard.trend_chart, dashboard.capacity_chart, dashboard.status_chart)
            points = [series.points() for series in dashboard.trend_chart.series()]
            for theme in ("light", "modern", "dark", "light"):
                with self.subTest(language=window.translator.lang_code, theme=theme):
                    palette = self.save_theme(window, theme)
                    self.assertEqual(charts, (dashboard.trend_chart, dashboard.capacity_chart, dashboard.status_chart))
                    self.assertEqual(points, [series.points() for series in dashboard.trend_chart.series()])
                    self.assert_chart_colors(dashboard, palette)
                    self.assert_color(window.central_widget.palette().color(QPalette.Window), palette["bg_main"])
                    self.assert_color(window.sidebar_frame.palette().color(QPalette.Window), palette["bg_sidebar"])
                    self.assert_color(window.btn_dashboard.palette().color(QPalette.ButtonText), palette["text_muted"])
                    for field in window.findChildren(QLineEdit):
                        self.assert_color(field.palette().color(QPalette.Base), palette["input_bg"])
                        self.assert_color(field.palette().color(QPalette.Text), palette["text_main"])
                    for page in range(4):
                        window.view_settings.tab_group.button(page).click()
                        self.app.processEvents()
                        card = window.view_settings.stacked_widget.currentWidget().findChild(QFrame, "settings_card")
                        self.assert_color(card.palette().color(QPalette.Window), palette["bg_card"])
                        for label in card.findChildren(QLabel):
                            key = "accent" if label.objectName() == "accent_label" else "text_main"
                            self.assert_color(label.palette().color(QPalette.WindowText), palette[key])
                    self.assertEqual(window.styleSheet(), "")

    def test_navigation_filters_expansion_and_popup_selection_survive_switches(self):
        before = Path("theme-test.db").read_bytes()
        window = self.window
        for theme in ("light", "dark", "modern"):
            palette = self.save_theme(window, theme)
            window.btn_orders.click()
            window.btn_sub_overview.click()
            self.assertIs(window.stacked_widget.currentWidget(), window.view_orders)
            orders = window.view_orders
            orders.search_id.setText("ord-00001")
            self.app.processEvents()
            visible = [orders.scroll_layout.itemAt(i).widget() for i in range(orders.scroll_layout.count())
                       if not orders.scroll_layout.itemAt(i).widget().isHidden()]
            self.assertEqual(len(visible), 1)
            row = visible[0]
            QTest.mouseClick(row.summary_row, Qt.LeftButton)
            self.app.processEvents()
            self.assertEqual(row.summary_row.property("expanded"), row.summary_row.is_expanded)
            self.assertEqual(row.products_table.item(0, 0).text(), "THEME-1")
            self.assert_color(row.products_table.palette().color(QPalette.Text), palette["text_main"])
            self.assertEqual(row.summary_row.styleSheet(), "")
            orders.search_id.clear()
            orders.limit_filter.setCurrentIndex(orders.limit_filter.count() - 1)
            self.app.processEvents()
            self.assertEqual(orders.scroll_layout.count(), 4)
            for combo in window.findChildren(QComboBox):
                combo.showPopup()
                self.app.processEvents()
                popup = combo.view()
                self.assert_color(popup.palette().color(QPalette.Base), palette["bg_card"])
                self.assert_color(popup.palette().color(QPalette.Text), palette["text_main"])
                combo.hidePopup()
            window.btn_dashboard.click()
            self.assertIs(window.stacked_widget.currentWidget(), window.view_dashboard)
            window.view_dashboard.time_filter.setCurrentIndex(2)
            self.assertEqual(window.view_dashboard.time_filter.currentIndex(), 2)
            self.assert_chart_colors(window.view_dashboard, palette)
        self.assertEqual(Path("theme-test.db").read_bytes(), before)

    def test_new_charts_and_reloaded_slices_use_the_active_theme(self):
        palette = self.save_theme(self.window, "light")
        dashboard = DashboardView(self.window.translator, self.window.dashboard_ctrl)
        self.widgets.append(dashboard)
        dashboard.load_real_data()
        self.assert_chart_colors(dashboard, palette)
        palette = self.save_theme(self.window, "modern")
        dashboard.load_real_data()
        self.assert_chart_colors(dashboard, palette)


if __name__ == "__main__":
    unittest.main()
