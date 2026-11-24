"""Actual unified-session UI, localization, themes, and no-membership state."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication, QDialog
from controllers.auth_controller import AuthError
from controllers.sales_controller import SalesController
from utils.theme_manager import ThemeManager
from utils.translations import translator
from views.session_host import SessionHost
from views.shop_admin_view import ShopAdminDialog
import test_shop_operations as operations


ROOT = Path(__file__).resolve().parents[1]


class ShopUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from PySide6.QtGui import QFontDatabase
        for name in ('segoeui.ttf','segoeuib.ttf'):
            QFontDatabase.addApplicationFont(str(Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/name))

    def setUp(self):
        self.case = operations.ShopOperationsTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        config = dict(paths=dict(database=self.case.path),localization=dict(language='en'),appearance=dict(theme='light'))
        with patch('views.session_host.QTimer.singleShot'):
            self.host = SessionHost(config,translator('en',str(ROOT/'utils')))
        self.addCleanup(self.close_host)

    def close_host(self):
        self.host.close()
        self.host.deleteLater()
        self.app.processEvents()

    def test_employee_without_assignments_can_sign_in_without_business_access(self):
        self.host.auth.sign_in('admin','password')
        self.host.auth.create_account('no-shops','temporary')
        self.host.auth.sign_in('no-shops','temporary')
        self.host.auth.change_password('temporary','employee-password')
        with patch('views.session_host.CredentialsDialog') as dialog:
            dialog.return_value.exec.return_value = QDialog.Accepted
            self.host.login()
        self.assertIsNone(self.host.main)
        self.assertFalse(self.host.no_access.isHidden())
        self.assertEqual(self.host.shops.count(),0)
        with self.assertRaises(AuthError):
            SalesController(self.case.path).choices()

    def test_session_and_admin_dialog_render_in_both_languages_and_all_themes(self):
        self.host.auth.sign_in('admin','password')
        self.host.install(1,1)
        self.host.show()
        evidence = os.environ.get('FINAL_RUN_EVIDENCE')
        for lang in ('pl','en'):
            for theme in ('light','dark','modern'):
                ThemeManager.apply_theme(self.app,theme,'medium')
                config = dict(self.host.config,localization=dict(language=lang),appearance=dict(theme=theme,font_size='medium'))
                self.host.main.apply_preferences(config)
                self.app.processEvents()
                self.assertEqual(self.host.width(),1280)
                self.assertEqual(self.host.shops.count(),2)
                self.assertEqual(self.host.warehouses.count(),2)
                self.assertEqual(self.host.buttons['shop_manage'].text(),self.host.translator.t('shop_manage'))
                dialog = ShopAdminDialog(self.host.auth,self.host.translator,self.host)
                dialog.show()
                self.app.processEvents()
                try:
                    self.assertEqual(dialog.warehouses.count(),2)
                    self.assertTrue(dialog.all_shops.text())
                    if evidence:
                        Path(evidence).mkdir(parents=True,exist_ok=True)
                        self.host.grab().save(str(Path(evidence)/f'session-{lang}-{theme}.png'))
                        dialog.grab().save(str(Path(evidence)/f'admin-{lang}-{theme}.png'))
                finally:
                    dialog.close()
                    dialog.deleteLater()
                    self.app.processEvents()


if __name__=='__main__':
    unittest.main()
