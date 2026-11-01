"""Actual dialog workflows refresh configured-database views without local styles."""

import json
import os
from pathlib import Path
import unittest

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QDialog, QTableWidget

from main import MainWindow
from utils.theme_manager import ThemeManager
from utils.translations import translator
from views.picking.pick_dialogs import AllocationDialog, OrderSelectionDialog, ShortageDialog
import test_pick_lists as picking


ROOT = Path(__file__).resolve().parents[1]


class PickingUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        picking.PickListTests.setUpClass()

    def setUp(self):
        self.case = picking.PickListTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        previous = Path.cwd()
        os.chdir(self.case.case.temp_dir.name)
        self.addCleanup(os.chdir, previous)
        self.config = {"paths": {"database": self.case.case.db_path}, "appearance": {"theme": "light", "font_size": "medium"}, "localization": {"language": "en", "date_format": "YYYY-MM-DD"}}
        Path("config.json").write_text(json.dumps(self.config), encoding="utf-8")

    def window(self, language="en"):
        ThemeManager.apply_theme(QApplication.instance(), "light", "medium")
        window = MainWindow(self.config, translator(language, str(ROOT / "utils")))
        self.case.case.widgets.append(window)
        window.show()
        window.btn_sub_picklists.click()
        QApplication.processEvents()
        self.assertIs(window.stacked_widget.currentWidget(), window.view_picklists)
        return window

    def test_real_generate_start_pick_and_close_dialog_flow_refreshes_inventory_and_orders(self):
        fixture = self.case.case
        fixture.inventory.add_stock(self.case.product_id, 1, 3)
        fixture.inventory.add_stock(self.case.product_id, 2, 4)
        order_id = self.case.order([(self.case.product_id, 5)])
        window = self.window()
        view = window.view_picklists
        def allocate():
            dialog = QApplication.activeModalWidget()
            self.assertIsInstance(dialog, AllocationDialog)
            self.assertEqual(len(dialog.editors), 2)
            dialog.editors[0][2].setValue(3)
            dialog.editors[1][2].setValue(2)
            dialog.save()
        def select():
            dialog = QApplication.activeModalWidget()
            self.assertIsInstance(dialog, OrderSelectionDialog)
            dialog.table.selectRow(0)
            QTimer.singleShot(0, allocate)
            dialog.choose()
        QTimer.singleShot(0, select)
        view.generate_button.click()
        self.assertEqual(view.table.rowCount(), 2)
        self.assertEqual(view.current_list["status"], "PENDING")
        self.assertEqual(window.product_ctrl.get_products()[0]["available"], 2)
        view.start_button.click()
        self.assertEqual(fixture.sql("SELECT status_code FROM orders WHERE order_id = ?", (order_id,)), [("IN_PROGRESS",)])
        for row, quantity in ((0, 3), (1, 2)):
            view.table.selectRow(row)
            view.picked_total.setValue(quantity)
            view.confirm_button.click()
        view.close_button.click()
        self.assertEqual(view.current_list["status"], "CLOSED")
        self.assertFalse(view.start_button.isEnabled())
        self.assertFalse(view.confirm_button.isEnabled())
        self.assertEqual(fixture.sql("SELECT SUM(quantity) FROM inventory"), [(2,)])
        self.assertEqual(window.view_products.table.item(0, window.view_products.columns.index("available")).text(), "2")
        self.assertEqual(window.view_dashboard.capacity_data["weight"]["used"], 5)
        self.assertFalse(Path("warehouse.db").exists())

    def test_shortage_form_saves_once_refreshes_all_views_and_exposes_missing_history(self):
        fixture = self.case.case
        fixture.inventory.add_stock(self.case.product_id, 1, 3)
        order_id = self.case.order([(self.case.product_id, 3)])
        list_id = self.case.allocate([order_id])
        window = self.window("pl")
        view = window.view_picklists
        view.reload_lists(list_id)
        view.table.selectRow(0)
        def report():
            dialog = QApplication.activeModalWidget()
            self.assertIsInstance(dialog, ShortageDialog)
            dialog.actual.setValue(0)
            dialog.save()
            dialog.save()
        QTimer.singleShot(0, report)
        view.shortage_button.click()
        self.assertIn(str(order_id), view.message.text())
        self.assertEqual(view.table.item(0, 7).text(), view.t("pick_line_cancelled"))
        self.assertEqual(len(self.case.controller.get_missing_stock()), 1)
        self.assertEqual(window.product_ctrl.get_products()[0]["available"], 0)
        self.assertEqual(window.view_dashboard.capacity_data["weight"]["used"], 0)
        def inspect_history():
            dialog = QApplication.activeModalWidget()
            table = dialog.findChild(QTableWidget)
            self.assertEqual(table.rowCount(), 1)
            self.assertEqual(table.item(0, 1).text(), "3")
            self.assertTrue(table.item(0, 4).text())
            dialog.reject()
        QTimer.singleShot(0, inspect_history)
        view.missing_button.click()
        view.close_button.click()
        self.assertEqual(view.current_list["status"], "CLOSED")

    def test_allocation_validation_and_theme_switches_preserve_data_in_both_languages(self):
        fixture = self.case.case
        fixture.inventory.add_stock(self.case.product_id, 1, 4)
        order_id = self.case.order([(self.case.product_id, 4)])
        before = fixture.dump()
        for language in ("en", "pl"):
            window = self.window(language)
            for theme in ("dark", "light", "modern"):
                ThemeManager.apply_theme(QApplication.instance(), theme, "medium")
                QApplication.processEvents()
                self.assertEqual(window.view_picklists.palette().color(QPalette.Window), QColor(ThemeManager.get_palette(theme)["bg_main"]))
                dialog = AllocationDialog(window.translator, window.picklist_ctrl, [order_id], window)
                fixture.widgets.append(dialog)
                dialog.show()
                dialog.save()
                self.assertEqual(dialog.error_label.text(), window.translator.t("wh_error_allocation_mismatch"))
                self.assertNotEqual(dialog.result(), QDialog.Accepted)
                dialog.reject()
                self.assertEqual(window.view_picklists.styleSheet(), "")
        self.assertEqual(fixture.dump(), before)

    def test_stock_entry_updates_dashboard_without_restarting(self):
        window = self.window()
        window.btn_products.click()
        view = window.view_products
        view.table.selectRow(0)
        def receive():
            dialog = QApplication.activeModalWidget()
            dialog.location.setCurrentIndex(dialog.location.findData(1))
            dialog.quantity.setValue(2)
            dialog.save()
        QTimer.singleShot(0, receive)
        view.buttons["add_stock"].click()
        self.assertEqual(window.view_dashboard.capacity_data["weight"]["used"], 5)
        self.assertEqual(view.table.item(0, view.columns.index("physical")).text(), "2")


if __name__ == "__main__":
    unittest.main()
