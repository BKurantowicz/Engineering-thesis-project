"""Own the operational window lifecycle; no warehouse UI exists before login."""
from copy import deepcopy
from pathlib import Path
import sqlite3
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QDialog, QMessageBox, QFileDialog)
from controllers import auth_controller
from controllers.auth_controller import AuthController
from controllers.warehouse_registry import WarehouseRegistry
from controllers.settings_controller import SettingsController
from models.database import DatabaseManager
from views.session_view import CredentialsDialog, AccountsDialog


class SessionHost(QMainWindow):
    def __init__(self, config, translator):
        super().__init__()
        self.config, self.translator = config, translator
        self.auth = AuthController(config.get('paths',{}).get('accounts') or 'accounts.db')
        auth_controller.runtime = self.auth
        self.registry = WarehouseRegistry(self.auth)
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
        self.warehouses = QComboBox()
        self.warehouses.setMinimumWidth(0)
        self.warehouses.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.warehouses.setMinimumContentsLength(18)
        self.bar.addWidget(self.warehouses)
        self.warehouses.activated.connect(self.switch)
        self.buttons = {}
        for key, slot in (('warehouse_create',self.create),('warehouse_register',self.register),
                          ('auth_accounts',self.accounts),('auth_change',self.change_password),('auth_logout',self.logout)):
            button = QPushButton()
            button.clicked.connect(lambda checked=False,method=slot: self.guarded(method))
            self.buttons[key] = button
            self.bar.addWidget(button)
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
            button.setEnabled(enabled and (key not in ('warehouse_create','warehouse_register','auth_accounts') or self.auth.session['role']=='admin'))
        self.login_button.setVisible(not enabled)

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
            paths = self.registry.paths()
            default = self.auth.active_warehouse() or str(Path(self.config.get('paths',{}).get('database','warehouse.db')).resolve())
            if not paths and self.auth.require()['role']=='admin':
                if Path(default).exists():
                    self.registry.register(default)
                else:
                    self.registry.create(default)
                paths = self.registry.paths()
            if not paths:
                raise ValueError('warehouse_unregistered')
            self.install(default if default in paths else paths[0])
            self.set_access(True)
        except Exception:
            self.auth.sign_out()
            raise

    def install(self, path):
        from main import MainWindow
        path = self.registry.activate(path)
        config = deepcopy(self.config)
        config.setdefault('paths',{})['database'] = path
        previous_path = self.auth.warehouse
        self.auth.warehouse = path
        try:
            candidate = MainWindow(config,self.translator,self.auth)
            self.auth.remember_warehouse(path)
        except Exception:
            self.auth.warehouse = previous_path
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
        self.identity.setText(self.auth.session['login'] + ' / ' + self.auth.session['role'])
        self.refresh_paths()

    def refresh_paths(self):
        self.warehouses.blockSignals(True)
        self.warehouses.clear()
        for path in self.registry.paths():
            self.warehouses.addItem(f'{Path(path).name} - {Path(path).parent}',path)
            self.warehouses.setItemData(self.warehouses.count()-1,path,Qt.ToolTipRole)
        self.warehouses.setCurrentIndex(self.warehouses.findData(self.auth.warehouse))
        self.warehouses.setToolTip(self.auth.warehouse or '')
        self.warehouses.blockSignals(False)

    def discard(self):
        # Explicit confirmation also protects drafts in settings and new operation forms.
        box = QMessageBox(QMessageBox.Question,self.translator.t('session_discard_title'),self.translator.t('session_discard'),parent=self)
        proceed = box.addButton(self.translator.t('discard_proceed'),QMessageBox.DestructiveRole)
        stay = box.addButton(self.translator.t('session_stay'),QMessageBox.RejectRole)
        box.setDefaultButton(stay)
        box.exec()
        return box.clickedButton() is proceed

    def switch(self):
        path = self.warehouses.currentData()
        if path == self.auth.warehouse:
            return
        if not self.discard():
            self.refresh_paths()
            return
        try:
            self.install(path)
        except (ValueError,OSError,sqlite3.Error) as error:
            self.refresh_paths()
            QMessageBox.warning(self,self.translator.t('operation_failed'),self.translator.t(str(error),self.translator.t('warehouse_invalid')))

    def logout(self):
        if not self.discard():
            return
        self.auth.sign_out()
        self.auth.warehouse = None
        if self.main:
            self.controls.setParent(self.centralWidget())
            self.layout.insertWidget(0,self.controls)
            self.layout.removeWidget(self.main)
            self.main.hide()
            self.main.deleteLater()
            self.main = None
        self.set_access(False)

    def create(self):
        path,_ = QFileDialog.getSaveFileName(self,self.translator.t('warehouse_create'),'warehouse.db','SQLite (*.db *.sqlite *.sqlite3)')
        if path:
            self.registry.create(path)
            self.refresh_paths()

    def register(self):
        path,_ = QFileDialog.getOpenFileName(self,self.translator.t('warehouse_register'),'','SQLite (*.db *.sqlite *.sqlite3)')
        if path:
            self.registry.register(path)
            self.refresh_paths()

    def accounts(self):
        AccountsDialog(self.auth,self.translator,self).exec()

    def change_password(self):
        CredentialsDialog(self.auth,self.translator,'change',self).exec()

    def closeEvent(self, event):
        self.auth.sign_out()
        super().closeEvent(event)
