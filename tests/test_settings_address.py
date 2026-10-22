"""Regression coverage for company-address persistence using isolated JSON files."""

import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from controllers.settings_controller import SettingsController
from utils.theme_manager import ThemeManager
from utils.translations import translator
from views.settings.settings_view import SettingsView


TRANSLATIONS_DIR = Path(__file__).resolve().parents[1] / "utils"


class SettingsAddressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.config_path = Path(self.temp_dir.name) / "config.json"
        self.controller = SettingsController(str(self.config_path))
        self.config = {
            "company_info": {
                "name": "Example Company",
                "tax_id": "1234567890",
                "street": "Main Street 10",
                "postal_code": "00-001",
                "city": "Warsaw",
                "email": "office@example.test",
                "phone": "+48 123 456 789",
                "additional_reference": "preserve this value",
            },
            "paths": {
                "database": "unused-test-database.db",
                "backups": "test-backups",
                "exports_pick_lists": "test-pick-lists",
                "exports_invoices": "test-invoices",
                "imports_default": "test-imports",
                "templates": {"base_dir": "test-templates", "invoice": "invoice.html"},
            },
            "email_smtp": {"smtp_key": "test-only-key", "host": "mail.example.test"},
            "localization": {"language": "en", "date_format": "YYYY-MM-DD", "currency": "PLN"},
            "appearance": {"theme": "dark", "font_size": "medium"},
            "system": {
                "auto_backup_on_exit": False,
                "notifications": {"show_toasts": False, "play_sound": False},
            },
            "extension_settings": {"enabled": True},
        }
        self.write_config(self.config)
        self.views = []
        self.addCleanup(self.close_views)
        original_stylesheet = self.app.styleSheet()
        self.addCleanup(self.app.setStyleSheet, original_stylesheet)
        message_box = patch("PySide6.QtWidgets.QMessageBox.information")
        self.message_box = message_box.start()
        self.addCleanup(message_box.stop)

    def write_config(self, config):
        self.config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

    def read_config(self):
        return json.loads(self.config_path.read_text(encoding="utf-8"))

    def open_view(self):
        language = self.controller.get_config()["localization"]["language"]
        view = SettingsView(translator(language, str(TRANSLATIONS_DIR)), self.controller)
        self.views.append(view)
        view.load_settings()
        return view

    def close_views(self):
        for view in self.views:
            view.close()
            view.deleteLater()
        self.app.processEvents()

    def test_repeated_save_and_reopen_preserves_each_address_component(self):
        expected = self.controller.get_config()
        for cycle in range(3):
            with self.subTest(cycle=cycle):
                view = self.open_view()
                self.assertEqual(view.comp_street.text(), "Main Street 10")
                self.assertEqual(view.comp_postal_code.text(), "00-001")
                self.assertEqual(view.comp_city.text(), "Warsaw")
                view.save_btn.click()
                self.assertEqual(self.read_config(), expected)
                view.close()
        self.assertEqual(self.message_box.call_count, 3)

    def test_editing_one_component_preserves_other_values_and_settings(self):
        for field, value in (
            ("street", "Długa 12/3, Building B"),
            ("postal_code", "90-001"),
            ("city", "Łódź"),
        ):
            with self.subTest(field=field):
                self.write_config(self.config)
                expected = copy.deepcopy(self.controller.get_config())
                expected["company_info"][field] = value
                view = self.open_view()
                getattr(view, "comp_" + field).setText(value)
                view.save_btn.click()
                self.assertEqual(self.read_config(), expected)
                reopened = self.open_view()
                self.assertEqual(getattr(reopened, "comp_" + field).text(), value)

    def test_malformed_address_is_preserved_until_explicitly_corrected(self):
        malformed = "Main Street 10, 00-001 Warsaw, 00-001 Warsaw"
        self.config["company_info"]["street"] = malformed
        self.write_config(self.config)
        expected = self.controller.get_config()
        view = self.open_view()
        self.assertEqual(view.comp_street.text(), malformed)
        view.save_btn.click()
        self.assertEqual(self.read_config(), expected)

        view = self.open_view()
        view.comp_street.setText("Main Street 10")
        view.save_btn.click()
        expected["company_info"]["street"] = "Main Street 10"
        self.assertEqual(self.read_config(), expected)
        self.assertEqual(self.open_view().comp_street.text(), "Main Street 10")

    def test_missing_address_components_can_be_entered_without_schema_migration(self):
        del self.config["company_info"]["postal_code"]
        del self.config["company_info"]["city"]
        self.write_config(self.config)
        expected = self.controller.get_config()
        view = self.open_view()
        self.assertEqual(view.comp_postal_code.text(), "")
        self.assertEqual(view.comp_city.text(), "")
        view.comp_postal_code.setText("00-001")
        view.comp_city.setText("Warsaw")
        view.save_btn.click()
        expected["company_info"].update(postal_code="00-001", city="Warsaw")
        self.assertEqual(self.read_config(), expected)

    def test_localized_address_fields_preserve_layout_and_theme_settings(self):
        labels = {
            "en": {"Street:", "Postal Code:", "City:"},
            "pl": {"Ulica:", "Kod pocztowy:", "Miasto:"},
        }
        for language in ("en", "pl"):
            for theme in ("dark", "light", "modern"):
                for font_size in ("small", "medium", "large"):
                    with self.subTest(language=language, theme=theme, font_size=font_size):
                        self.config["localization"]["language"] = language
                        self.config["appearance"].update(theme=theme, font_size=font_size)
                        self.write_config(self.config)
                        expected = self.controller.get_config()
                        view = self.open_view()
                        view.resize(1100, 750)
                        view.stacked_widget.setCurrentWidget(view.page_company)
                        view.show()
                        view.save_btn.click()
                        self.app.processEvents()

                        self.assertEqual(view.stacked_widget.count(), 4)
                        visible_labels = {label.text() for label in view.page_company.findChildren(QLabel)}
                        self.assertTrue(labels[language].issubset(visible_labels))
                        for field in (view.comp_street, view.comp_postal_code, view.comp_city):
                            self.assertTrue(field.isVisible())
                            self.assertGreater(field.width(), 0)
                            self.assertGreaterEqual(field.height(), field.minimumSizeHint().height())
                        self.assertEqual(self.read_config(), expected)
                        self.assertEqual(self.app.styleSheet(), ThemeManager.get_stylesheet(theme, font_size))
                        view.close()


if __name__ == "__main__":
    unittest.main()
