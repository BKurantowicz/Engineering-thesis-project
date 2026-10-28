"""Exercise actual Settings dropdown palettes and input with temporary config."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from controllers.settings_controller import SettingsController
from utils.translations import translator
from views.settings.settings_view import SettingsView


TRANSLATIONS_DIR = Path(__file__).resolve().parents[1] / "utils"
OPTIONS = {
    "cb_lang": ["en", "pl"],
    "cb_theme": ["dark", "light", "modern"],
    "cb_font": ["small", "medium", "large"],
    "cb_date": ["YYYY-MM-DD", "DD.MM.YYYY"],
}


def contrast_ratio(foreground, background):
    def luminance(color):
        channels = [color.redF(), color.greenF(), color.blueF()]
        linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
                  for v in channels]
        return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

    first, second = sorted((luminance(foreground), luminance(background)))
    return (second + 0.05) / (first + 0.05)


class SettingsDropdownTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.config_path = Path(self.temp_dir.name) / "settings.json"
        self.controller = SettingsController(str(self.config_path))
        self.views = []
        self.addCleanup(self.close_views)
        self.addCleanup(self.app.setStyleSheet, self.app.styleSheet())
        dialog = patch("PySide6.QtWidgets.QMessageBox.information")
        dialog.start()
        self.addCleanup(dialog.stop)

    def close_views(self):
        for view in self.views:
            view.close()
            view.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)

    def open_view(self, language="en"):
        view = SettingsView(translator(language, str(TRANSLATIONS_DIR)), self.controller)
        self.views.append(view)
        view.load_settings()
        view.resize(1100, 650)
        view.stacked_widget.setCurrentIndex(2)
        view.show()
        self.app.processEvents()
        return view

    def assert_readable(self, widget, foreground, background):
        palette = widget.palette()
        self.assertGreaterEqual(
            contrast_ratio(palette.color(foreground), palette.color(background)),
            4.5,
            f"Unreadable palette: {palette.color(foreground).name()} on "
            f"{palette.color(background).name()}",
        )

    def test_every_dropdown_after_theme_switch_in_both_languages_and_all_font_sizes(self):
        for language in ("en", "pl"):
            for font_size, pixels in (("small", 12), ("medium", 14), ("large", 16)):
                view = self.open_view(language)
                self.assertEqual(view.stacked_widget.count(), 4)
                view.cb_lang.setCurrentText(language)
                view.cb_font.setCurrentText(font_size)
                for theme in ("dark", "light", "modern", "light"):
                    with self.subTest(language=language, font=font_size, theme=theme):
                        view.cb_theme.setCurrentText(theme)
                        view.save_btn.click()
                        self.app.processEvents()
                        for name, expected_options in OPTIONS.items():
                            combo = getattr(view, name)
                            self.assertEqual([combo.itemText(i) for i in range(combo.count())],
                                             expected_options)
                            self.assertEqual(combo.font().pixelSize(), pixels)
                            combo.setFocus()
                            self.app.processEvents()
                            self.assert_readable(combo, QPalette.Text, QPalette.Base)
                            combo.showPopup()
                            self.app.processEvents()
                            popup = combo.view()
                            self.assertTrue(popup.isVisible())
                            self.assert_readable(popup, QPalette.Text, QPalette.Base)
                            self.assert_readable(popup, QPalette.HighlightedText, QPalette.Highlight)
                            QTest.keyClick(popup, Qt.Key_End)
                            self.app.processEvents()
                            self.assertTrue(popup.currentIndex().isValid())
                            selected = popup.visualRect(popup.currentIndex())
                            painted = popup.viewport().grab().toImage()
                            self.assertEqual(
                                painted.pixelColor(selected.right() - 8, selected.center().y()).name(),
                                popup.palette().color(QPalette.Highlight).name(),
                                "The highlighted option must paint with the current shared theme",
                            )
                            combo.hidePopup()
                        saved = json.loads(self.config_path.read_text(encoding="utf-8"))
                        self.assertEqual(saved["appearance"], {"theme": theme, "font_size": font_size})
                        self.assertEqual(saved["localization"]["language"], language)
                view.close()

    def test_keyboard_and_mouse_selection_save_and_reopen_all_existing_bindings(self):
        view = self.open_view()
        for name, options in OPTIONS.items():
            with self.subTest(dropdown=name):
                combo = getattr(view, name)
                combo.showPopup()
                self.app.processEvents()
                QTest.keyClick(combo.view(), Qt.Key_End)
                QTest.keyClick(combo.view(), Qt.Key_Return)
                self.assertEqual(combo.currentText(), options[-1])
                combo.showPopup()
                self.app.processEvents()
                first = combo.model().index(0, 0)
                position = combo.view().visualRect(first).center()
                QTest.mouseClick(combo.view().viewport(), Qt.LeftButton, pos=position)
                self.assertEqual(combo.currentText(), options[0])
                QTest.keyClick(combo, Qt.Key_End)
                self.assertEqual(combo.currentText(), options[-1])
        view.save_btn.click()
        reopened = self.open_view("pl")
        for name, options in OPTIONS.items():
            self.assertEqual(getattr(reopened, name).currentText(), options[-1])
        self.assertEqual(reopened.stacked_widget.count(), 4)
        self.assertFalse(list(Path(self.temp_dir.name).glob("*.db")))


if __name__ == "__main__":
    unittest.main()
