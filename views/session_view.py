"""Authentication gateway and account management for the desktop application."""
import sqlite3
from PySide6.QtWidgets import (QDialog, QFormLayout, QLineEdit, QLabel, QPushButton,
    QVBoxLayout, QComboBox, QMessageBox, QDialogButtonBox)
from controllers.auth_controller import AuthError


class CredentialsDialog(QDialog):
    def __init__(self, auth, translator, mode='login', parent=None):
        super().__init__(parent)
        self.auth, self.t, self.mode = auth, translator.t, mode
        self.setWindowTitle(self.t('auth_' + mode))
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        self.login = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.new_password = QLineEdit()
        self.new_password.setEchoMode(QLineEdit.Password)
        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.Password)
        if mode != 'change':
            form.addRow(self.t('auth_login_name'), self.login)
        form.addRow(self.t('auth_password'), self.password)
        if mode == 'change':
            form.addRow(self.t('auth_new_password_label'), self.new_password)
        if mode != 'login':
            form.addRow(self.t('auth_confirm_password'), self.confirm)
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(self.t('auth_' + mode))
        buttons.button(QDialogButtonBox.Cancel).setText(self.t('prod_cancel'))
        buttons.accepted.connect(self.submit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def submit(self):
        try:
            if self.mode != 'login' and self.confirm.text() != (self.new_password.text() if self.mode == 'change' else self.password.text()):
                raise AuthError('auth_password_mismatch')
            if self.mode == 'login':
                self.auth.sign_in(self.login.text(), self.password.text())
            elif self.mode == 'change':
                self.auth.change_password(self.password.text(), self.new_password.text())
            else:
                self.auth.create_account(self.login.text(), self.password.text(), first=self.mode == 'setup')
            self.accept()
        except (ValueError, OSError, sqlite3.Error) as error:
            self.error.setText(self.t(str(error), self.t('auth_invalid')))


class AccountsDialog(QDialog):
    def __init__(self, auth, translator, parent=None):
        super().__init__(parent)
        auth.require(True)
        self.setWindowTitle(translator.t('auth_accounts'))
        layout = QVBoxLayout(self)
        create = QPushButton(translator.t('auth_create'))
        layout.addWidget(create)
        employees = QComboBox()
        layout.addWidget(employees)
        def reload():
            employees.clear()
            for row in auth.employees():
                employees.addItem(row['login'], row['user_id'])
        def add():
            CredentialsDialog(auth, translator, 'create', self).exec()
            reload()
        create.clicked.connect(add)
        password = QLineEdit()
        password.setEchoMode(QLineEdit.Password)
        password.setPlaceholderText(translator.t('auth_new_password_label'))
        layout.addWidget(password)
        reset = QPushButton(translator.t('auth_reset'))
        layout.addWidget(reset)
        def save():
            try:
                auth.reset_password(employees.currentData(), password.text())
                password.clear()
                QMessageBox.information(self, translator.t('auth_accounts'), translator.t('auth_reset_done'))
            except (ValueError, sqlite3.Error) as error:
                QMessageBox.warning(self, translator.t('auth_accounts'), translator.t(str(error)))
        reset.clicked.connect(save)
        reload()
