"""Translated customer Add/Edit form; the controller owns validation and writes."""

import sqlite3

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout

from controllers.customer_controller import CustomerValidationError


class CustomerDialog(QDialog):
    def __init__(self, translator, controller, customer_id=None, parent=None):
        super().__init__(parent)
        self.t = translator.t
        self.controller = controller
        self.customer_id = customer_id
        self.saved_customer_id = None
        self.setWindowTitle(self.t("cust_edit" if customer_id is not None else "cust_add"))
        self.resize(520, 420)
        layout = QVBoxLayout(self)
        hint = QLabel(self.t("cust_required_hint"))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        form = QFormLayout()
        self.fields = {}
        for field in controller.FIELDS:
            editor = QLineEdit()
            editor.setObjectName("customer_" + field)
            label = self.t("cust_" + field)
            if field in controller.REQUIRED_FIELDS:
                label += " *"
            form.addRow(label, editor)
            self.fields[field] = editor
        layout.addLayout(form)
        self.error_label = QLabel()
        self.error_label.setObjectName("error_label")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText(self.t("cust_save"))
        self.buttons.button(QDialogButtonBox.Save).setObjectName("primary_btn")
        self.buttons.button(QDialogButtonBox.Cancel).setText(self.t("cust_cancel"))
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        if customer_id is not None:
            customer = controller.get_customer(customer_id)
            for field, editor in self.fields.items():
                editor.setText(customer[field] or "")

    def save(self):
        if self.saved_customer_id is not None:
            return
        self.error_label.clear()
        values = {field: editor.text() for field, editor in self.fields.items()}
        try:
            self.saved_customer_id = self.controller.save_customer(values, self.customer_id)
        except CustomerValidationError as error:
            self.error_label.setText(self.t("cust_error_" + error.code).format(
                field=self.t("cust_" + error.field) if error.field else "",
            ))
            if error.field in self.fields:
                self.fields[error.field].setFocus()
            return
        except sqlite3.Error:
            self.error_label.setText(self.t("cust_error_storage"))
            return
        self.buttons.button(QDialogButtonBox.Save).setEnabled(False)
        self.accept()
