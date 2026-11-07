"""External template selection survives save/reopen and filesystem changes."""
import gc
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QMessageBox
from controllers.settings_controller import SettingsController
from utils.document_templates import BUNDLED_DIR
from utils.translations import translator
from views.settings.settings_view import SettingsView


class TemplateSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_external_refresh_save_reopen_and_deleted_selection_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            config_path=root/"config.json"
            controller=SettingsController(str(config_path))
            config=controller.get_config()
            config["paths"]["templates"]={"base_dir":str(root)}
            config_path.write_text(json.dumps(config),encoding="utf8")
            for kind in ("email","pick","invoice"):
                for variant in ("standard","compact"):
                    name=f"{kind}-{variant}.html"
                    (root/name).write_text((BUNDLED_DIR/name).read_text(encoding="utf8"),encoding="utf8")
            lang=translator("pl",str(Path(__file__).resolve().parents[1]/"utils"))
            view=SettingsView(lang,controller)
            view.load_settings()
            for kind,combo in view.template_choices.items():
                self.assertEqual(combo.count(),2)
                combo.setCurrentIndex(combo.findData(f"{kind}-compact.html"))
            with patch.object(QMessageBox,"information"),patch.object(QMessageBox,"warning"):
                view.save_settings()
            view.close()
            reopened=SettingsView(lang,controller)
            reopened.load_settings()
            self.assertEqual(reopened.template_choices["email"].currentData(),"email-compact.html")
            (root/"email-compact.html").unlink()
            reopened.refresh_templates()
            self.assertEqual(reopened.template_choices["email"].currentData(),"email-compact.html")
            self.assertTrue(reopened.template_notice.text())
            combo=reopened.template_choices["email"]
            combo.setCurrentIndex(combo.findData("email-standard.html"))
            self.assertEqual(reopened.template_notice.text(),"")
            (root/"email-new.html").write_text((BUNDLED_DIR/"email-standard.html").read_text(encoding="utf8"),encoding="utf8")
            reopened.refresh_templates()
            self.assertGreaterEqual(reopened.template_choices["email"].findData("email-new.html"),0)
            reopened.close()
            del view,reopened
            gc.collect()


if __name__=="__main__":
    unittest.main()
