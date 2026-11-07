"""Exercise row selection and rendered interaction contrast, not just QSS text."""

from contextlib import closing
import gc
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (QApplication, QDialog, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from models.database import DatabaseManager
from utils.theme_manager import ThemeManager
from utils.translations import translator
from views.orders.orders_view import OrdersView


ROOT = Path(__file__).resolve().parents[1]


def contrast(first, second):
    def luminance(color):
        channels = (color.redF(), color.greenF(), color.blueF())
        linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]
        return sum(c * w for c, w in zip(linear, (.2126, .7152, .0722)))
    low, high = sorted((luminance(first), luminance(second)))
    return (high + .05) / (low + .05)


class SelectionContrastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.widgets = []
        self.addCleanup(self.app.setPalette, self.app.palette())
        self.addCleanup(self.app.setStyleSheet, self.app.styleSheet())
        self.addCleanup(self.close_widgets)

    def close_widgets(self):
        for widget in self.widgets:
            widget.close()
            widget.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        gc.collect()

    def show(self, widget, width=900, height=450):
        self.widgets.append(widget)
        widget.resize(width, height)
        widget.show()
        widget.activateWindow()
        self.app.processEvents()
        return widget

    def test_tables_select_and_paint_whole_rows_with_and_without_focus(self):
        for theme in ("light", "dark", "modern"):
            with self.subTest(theme=theme):
                ThemeManager.apply_theme(self.app, theme, "medium")
                window = QDialog()
                layout = QVBoxLayout(window)
                table = QTableWidget(2, 3)
                for row in range(2):
                    for column in range(3):
                        table.setItem(row, column, QTableWidgetItem(f"Cell {row}, {column}"))
                other = QLineEdit("Move focus here")
                layout.addWidget(table)
                layout.addWidget(other)
                self.show(window)
                QTest.mouseClick(table.viewport(), Qt.LeftButton, pos=table.visualItemRect(table.item(0, 1)).center())
                self.assertEqual(len(table.selectedItems()), 3)
                for focused in (True, False):
                    (table if focused else other).setFocus()
                    self.app.processEvents()
                    picture = table.viewport().grab().toImage()
                    backgrounds = []
                    for column in range(3):
                        rect = table.visualItemRect(table.item(0, column))
                        backgrounds.append(picture.pixelColor(rect.right() - 8, rect.top() + 5))
                    self.assertEqual(len({color.name() for color in backgrounds}), 1, [color.name() for color in backgrounds])
                    unselected = table.visualItemRect(table.item(1, 2))
                    self.assertNotEqual(backgrounds[0], picture.pixelColor(unselected.right() - 8, unselected.top() + 5))
                    for group in (QPalette.Active, QPalette.Inactive):
                        self.assertGreaterEqual(contrast(table.palette().color(group, QPalette.HighlightedText), backgrounds[0]), 4.5)
                    self.assertGreaterEqual(table.visualItemRect(table.item(0, 2)).right(), table.viewport().width() - 4)
                window.close()

    def test_orders_mouse_keyboard_range_and_theme_changes_preserve_selection_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "orders.db")
            DatabaseManager(path)
            with closing(sqlite3.connect(path)) as db, db:
                db.executemany("INSERT INTO orders(order_id,status_code,total_amount) VALUES(?,'NEW',0)", [(1,), (2,), (3,)])
                before = list(db.iterdump())
            view = self.show(OrdersView(translator("en", str(ROOT / "utils")), path), 1400, 700)
            rows = view.order_rows
            QTest.mouseClick(rows[0].summary_row, Qt.LeftButton)
            self.assertEqual(view.selected_order_ids, {rows[0].order_id})
            self.assertTrue(rows[0].summary_row.is_expanded)
            QTest.mouseClick(rows[1].summary_row, Qt.LeftButton, Qt.ControlModifier)
            self.assertEqual(view.selected_order_ids, {rows[0].order_id, rows[1].order_id})
            self.assertFalse(rows[1].summary_row.is_expanded)
            QTest.keyClick(rows[1].summary_row, Qt.Key_Down, Qt.ShiftModifier)
            self.assertEqual(view.selected_order_ids, {rows[1].order_id, rows[2].order_id})
            QTest.keyClick(rows[2].summary_row, Qt.Key_Return)
            self.assertTrue(rows[2].summary_row.is_expanded)
            QTest.keyClick(rows[2].summary_row, Qt.Key_Left)
            self.assertFalse(rows[2].summary_row.is_expanded)
            QTest.keyClick(rows[2].summary_row, Qt.Key_Home, Qt.ControlModifier)
            QTest.keyClick(rows[0].summary_row, Qt.Key_Space, Qt.ControlModifier)
            self.assertEqual(len(view.selected_order_ids), 3)
            view.search_id.setFocus()
            for theme in ("light", "dark", "modern"):
                ThemeManager.apply_theme(self.app, theme, "medium")
                self.app.processEvents()
                for row in rows:
                    self.assertTrue(row.summary_row.property("selected"))
                    picture = row.summary_row.grab().toImage()
                    background = picture.pixelColor(3, picture.height() // 2)
                    self.assertEqual(background, picture.pixelColor(picture.width() - 4, picture.height() // 2))
                    label = row.summary_row.findChild(QLabel)
                    self.assertGreaterEqual(contrast(label.palette().color(QPalette.WindowText), background), 4.5)
            selected = set(view.selected_order_ids)
            view.load_orders()
            self.assertEqual(view.selected_order_ids, selected)
            QTest.keyClick(view.order_rows[0].summary_row, Qt.Key_Escape)
            self.assertEqual(view.selected_order_ids, set())
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(list(db.iterdump()), before)
            view.close()
            self.close_widgets()
            self.widgets.clear()

    def test_rendered_buttons_tabs_and_inputs_keep_contrast_across_interaction_states(self):
        for theme in ("light", "dark", "modern"):
            ThemeManager.apply_theme(self.app, theme, "medium")
            p = ThemeManager.get_palette(theme)
            window = QDialog()
            layout = QVBoxLayout(window)
            buttons = []
            for name in ("secondary_btn", "primary_btn", "danger_btn", "action_btn", "tab_btn"):
                button = QPushButton("Readable action")
                button.setObjectName(name)
                buttons.append(button)
                layout.addWidget(button)
            field = QLineEdit("Readable input")
            tabs = QTabWidget()
            tabs.addTab(QWidget(), "Selected tab")
            tabs.addTab(QWidget(), "Other tab")
            layout.addWidget(field)
            layout.addWidget(tabs)
            self.show(window, 550, 550)
            for button in buttons:
                for state in ("hover", "pressed", "focus", "disabled"):
                    with self.subTest(theme=theme, button=button.objectName(), state=state):
                        button.setEnabled(state != "disabled")
                        QTest.mouseMove(button, button.rect().center())
                        if state == "pressed":
                            QTest.mousePress(button, Qt.LeftButton)
                        elif state == "focus":
                            QTest.mouseMove(field, field.rect().center())
                            button.setFocus()
                        self.app.processEvents()
                        picture = window.grab().toImage().copy(button.geometry())
                        background = picture.pixelColor(picture.width() // 2, 6)
                        foreground = QColor(p['text_muted'] if state == "disabled" else
                            '#ffffff' if button.objectName() in ("primary_btn", "danger_btn") or
                            state == "pressed" else
                            p['accent'] if button.objectName() == "action_btn" and state == "focus" else p['text_main'])
                        # Inspect actual text pixels as well as its contrast against the painted background.
                        matches = sum(picture.pixelColor(x, y) == foreground
                                      for x in range(8, picture.width() - 8)
                                      for y in range(8, picture.height() - 8))
                        if state == "pressed":
                            QTest.mouseRelease(button, Qt.LeftButton)
                        self.assertGreater(matches, 5, f"Expected readable text {foreground.name()}")
                        self.assertGreaterEqual(contrast(foreground, background), 4.5, (foreground.name(), background.name(), background.alpha()))
                button.setEnabled(True)
            for enabled in (True, False):
                field.setEnabled(enabled)
                field.setFocus()
                self.app.processEvents()
                group = QPalette.Active if enabled else QPalette.Disabled
                self.assertGreaterEqual(contrast(field.palette().color(group, QPalette.Text), field.palette().color(group, QPalette.Base)), 4.5)
            bar = tabs.tabBar()
            QTest.mouseMove(bar, bar.tabRect(1).center())
            self.app.processEvents()
            picture = bar.grab().toImage()
            for index in (0, 1):
                rect = bar.tabRect(index)
                background = picture.pixelColor(rect.center().x(), rect.top() + 4)
                foreground = QColor('#ffffff' if index == 0 else p['text_main'])
                self.assertGreaterEqual(contrast(foreground, background), 4.5)
            window.close()


if __name__ == "__main__":
    unittest.main()
