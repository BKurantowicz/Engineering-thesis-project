"""Own the operational window lifecycle; no warehouse UI exists before login."""
from copy import deepcopy
from pathlib import Path
import sqlite3
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QDialog, QMessageBox, QFileDialog)
from controllers import auth_controller
from controllers.auth_controller import AuthController
from controllers.shop_controller import ShopController
from models.application_runtime import initialize_application
from controllers.settings_controller import SettingsController
from models.database import DatabaseManager
from views.session_view import CredentialsDialog, AccountsDialog


class SessionHost(QMainWindow):
    def __init__(self, config, translator):
        super().__init__()
        self.config, self.translator = config, translator
        path = Path(config.get('paths',{}).get('database') or 'application.db')
        if path.name.lower() == 'warehouse.db':
            path = path.with_name('application.db')
        self.auth = AuthController(initialize_application(path))
        auth_controller.runtime = self.auth
        self.registry = ShopController(self.auth)
        self.main = None
        self.resize(1280,837)
        root = QWidget()
        self.setCentralWidget(root)
        self.layout = QVBoxLayout(root)
        self.layout.setContentsMargins(0,0,0,0)
        self.controls = QWidget()
        self.bar = QVBoxLayout(self.controls)
        self.bar.setContentsMargins(0,0,0,12)
        self.layout.addWidget(self.controls)
        self.identity = QLabel()
        self.bar.addWidget(self.identity)
        self.shop_label = QLabel()
        self.bar.addWidget(self.shop_label)
        self.shops = QComboBox()
        self.bar.addWidget(self.shops)
        self.shops.activated.connect(lambda: self.guarded(self.switch_shop))
        self.warehouse_label = QLabel()
        self.bar.addWidget(self.warehouse_label)
        self.warehouses = QComboBox()
        self.warehouses.setMinimumWidth(0)
        self.warehouses.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.warehouses.setMinimumContentsLength(18)
        self.bar.addWidget(self.warehouses)
        self.warehouses.activated.connect(lambda: self.guarded(self.switch))
        self.buttons = {}
        for key, slot in (('shop_manage',self.manage),
                          ('auth_accounts',self.accounts),('auth_change',self.change_password),('auth_logout',self.logout)):
            button = QPushButton()
            button.clicked.connect(lambda checked=False,method=slot: self.guarded(method))
            self.buttons[key] = button
            self.bar.addWidget(button)
        self.no_access = QLabel()
        self.no_access.setWordWrap(True)
        self.layout.addWidget(self.no_access)
        self.login_button = QPushButton()
        self.login_button.clicked.connect(lambda: self.guarded(self.login))
        self.layout.addWidget(self.login_button)
        self.retranslate()
        self.set_access(False)
        QTimer.singleShot(0,lambda: self.guarded(self.login))

    def retranslate(self, config=None):
        if config:
            self.config = config
            self.translator = self.main.translator
            self.main.sidebar_layout.insertWidget(0,self.controls)
            self.controls.show()
        self.setWindowTitle(self.translator.t('app_title','WMS'))
        self.login_button.setText(self.translator.t('auth_login'))
        self.no_access.setText(self.translator.t('shop_no_access'))
        self.shops.setAccessibleName(self.translator.t('shop_select'))
        self.warehouses.setAccessibleName(self.translator.t('warehouse_select'))
        self.shop_label.setText(self.translator.t('shop_select'))
        self.warehouse_label.setText(self.translator.t('warehouse_select'))
        for key, button in self.buttons.items():
            button.setText(self.translator.t(key))

    def guarded(self, method):
        try:
            method()
        except (ValueError, OSError, sqlite3.Error) as error:
            QMessageBox.warning(self,self.translator.t('operation_failed'),self.translator.t(str(error),self.translator.t('operation_failed')))

    def set_access(self, enabled):
        self.controls.setVisible(enabled)
        self.warehouses.setVisible(enabled)
        self.identity.setVisible(enabled)
        for key, button in self.buttons.items():
            button.setVisible(enabled)
            button.setEnabled(enabled and (key not in ('shop_manage','auth_accounts') or self.auth.session['role']=='admin'))
        self.login_button.setVisible(not enabled)
        self.no_access.setVisible(enabled and self.main is None)

    def login(self):
        if self.auth.needs_setup():
            if CredentialsDialog(self.auth,self.translator,'setup',self).exec() != QDialog.Accepted:
                return
        if CredentialsDialog(self.auth,self.translator,'login',self).exec() != QDialog.Accepted:
            return
        if self.auth.session['must_change']:
            if CredentialsDialog(self.auth,self.translator,'change',self).exec() != QDialog.Accepted:
                self.auth.sign_out()
                return
        try:
            shops = self.registry.shops()
            if shops:
                sid,wid = self.registry.last_context()
                if sid not in {s['shop_id'] for s in shops}:
                    sid = shops[0]['shop_id']
                warehouses = self.registry.warehouses(sid)
                if wid not in {w['warehouse_id'] for w in warehouses}:
                    wid = warehouses[0]['warehouse_id'] if warehouses else None
                self.install(sid,wid)
            self.refresh_paths()
            self.set_access(True)
        except Exception:
            self.auth.sign_out()
            raise

    def install(self, shop_id, warehouse_id=None):
        from main import MainWindow
        config = deepcopy(self.config)
        config.setdefault('paths',{})['database'] = self.auth.path
        previous_context = self.auth.shop_id,self.auth.warehouse_id,self.auth.warehouse,self.auth.epoch
        self.auth.select_context(shop_id,warehouse_id)
        candidate = None
        try:
            candidate = MainWindow(config,self.translator,self.auth)
            self.registry.remember_context()
        except Exception:
            self.auth.shop_id,self.auth.warehouse_id,self.auth.warehouse,self.auth.epoch = previous_context
            if candidate is not None:
                candidate.deleteLater()
            raise
        candidate.setWindowFlags(Qt.Widget)
        candidate.preferences_changed.connect(self.retranslate)
        previous = self.main
        previous_size = self.size()
        self.layout.removeWidget(self.controls)
        candidate.sidebar_layout.insertWidget(0,self.controls)
        self.controls.show()
        self.login_button.hide()
        self.main = candidate
        if previous:
            self.layout.removeWidget(previous)
            previous.hide()
            previous.deleteLater()
        self.layout.addWidget(candidate,1)
        candidate.show()
        self.resize(previous_size)
        self.config = config
        self.set_access(True)
        self.identity.setText(self.auth.session['login'] + ' / ' + self.auth.session['role'])
        self.refresh_paths()

    def refresh_paths(self):
        self.shops.blockSignals(True)
        self.warehouses.blockSignals(True)
        self.shops.clear()
        self.warehouses.clear()
        for shop in self.registry.shops():
            self.shops.addItem(shop['name'],shop['shop_id'])
        self.shops.setCurrentIndex(self.shops.findData(self.auth.shop_id))
        if self.auth.shop_id is not None:
            for warehouse in self.registry.warehouses(self.auth.shop_id):
                self.warehouses.addItem(warehouse['name'],warehouse['warehouse_id'])
        self.warehouses.setCurrentIndex(self.warehouses.findData(self.auth.warehouse_id))
        self.identity.setText(self.auth.session['login']+' / '+self.auth.session['role'])
        self.shops.blockSignals(False)
        self.warehouses.blockSignals(False)

    def discard(self):
        # Explicit confirmation also protects drafts in settings and new operation forms.
        box = QMessageBox(QMessageBox.Question,self.translator.t('session_discard_title'),self.translator.t('session_discard'),parent=self)
        proceed = box.addButton(self.translator.t('discard_proceed'),QMessageBox.DestructiveRole)
        stay = box.addButton(self.translator.t('session_stay'),QMessageBox.RejectRole)
        box.setDefaultButton(stay)
        box.exec()
        return box.clickedButton() is proceed

    def switch_shop(self):
        sid = self.shops.currentData()
        if sid == self.auth.shop_id:
            return
        if not self.discard():
            self.refresh_paths()
            return
        try:
            warehouses = self.registry.warehouses(sid)
            self.install(sid,warehouses[0]['warehouse_id'] if warehouses else None)
        finally:
            self.refresh_paths()

    def switch(self):
        wid = self.warehouses.currentData()
        if wid == self.auth.warehouse_id:
            return
        if not self.discard():
            self.refresh_paths()
            return
        try:
            self.install(self.auth.shop_id,wid)
        finally:
            self.refresh_paths()

    def logout(self):
        if not self.discard():
            return
        self.auth.sign_out()
        self.auth.shop_id = self.auth.warehouse_id = self.auth.warehouse = None
        if self.main:
            self.controls.setParent(self.centralWidget())
            self.layout.insertWidget(0,self.controls)
            self.layout.removeWidget(self.main)
            self.main.hide()
            self.main.deleteLater()
            self.main = None
        self.set_access(False)

    def manage(self):
        from views.shop_admin_view import ShopAdminDialog
        ShopAdminDialog(self.auth,self.translator,self).exec()
        warehouses = self.registry.warehouses(self.auth.shop_id)
        wid = self.auth.warehouse_id
        if wid not in {w['warehouse_id'] for w in warehouses}:
            wid = warehouses[0]['warehouse_id'] if warehouses else None
        self.install(self.auth.shop_id,wid)

    def accounts(self):
        AccountsDialog(self.auth,self.translator,self).exec()

    def change_password(self):
        CredentialsDialog(self.auth,self.translator,'change',self).exec()

    def closeEvent(self, event):
        self.auth.sign_out()
        super().closeEvent(event)
