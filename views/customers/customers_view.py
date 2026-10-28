"""Customer list providing reachable Add/Edit master-data forms."""

import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from controllers.customer_controller import CustomerValidationError
from views.customers.customer_dialog import CustomerDialog


class CustomersView(QWidget):
    COLUMNS = ("customer_id", "first_name", "last_name", "email", "phone", "city")

    def __init__(self, translator, controller):
        super().__init__()
        self.translator = translator
        self.t = translator.t
        self.controller = controller
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        title = QLabel(self.t("cust_title"))
        title.setObjectName("title_label")
        layout.addWidget(title)
        actions = QHBoxLayout()
        self.add_button = QPushButton(self.t("cust_add"))
        self.add_button.setObjectName("primary_btn")
        self.edit_button = QPushButton(self.t("cust_edit"))
        self.edit_button.setEnabled(False)
        self.add_button.clicked.connect(lambda: self.open_editor())
        self.edit_button.clicked.connect(lambda: self.open_editor(self.selected_customer_id()))
        actions.addWidget(self.add_button)
        actions.addWidget(self.edit_button)
        actions.addStretch()
        layout.addLayout(actions)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.conflict_message = QLabel()
        self.conflict_message.setObjectName("error_label")
        self.conflict_message.setWordWrap(True)
        layout.addWidget(self.conflict_message)
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([self.t("cust_" + field) for field in self.COLUMNS])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.itemSelectionChanged.connect(lambda: self.edit_button.setEnabled(self.selected_customer_id() is not None))
        layout.addWidget(self.table)
        self.load_customers()

    def selected_customer_id(self):
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        return item.data(Qt.UserRole) if item else None

    def load_customers(self, selected_id=None):
        self.table.setRowCount(0)
        self.message.clear()
        self.message.hide()
        self.conflict_message.clear()
        self.conflict_message.hide()
        try:
            customers = self.controller.get_customers()
            conflicts = self.controller.get_email_conflicts()
        except sqlite3.Error:
            self.message.setText(self.t("cust_error_storage"))
            self.message.show()
            return
        self.table.setRowCount(len(customers))
        for row, customer in enumerate(customers):
            for column, field in enumerate(self.COLUMNS):
                item = QTableWidgetItem("" if customer[field] is None else str(customer[field]))
                if column == 0:
                    item.setData(Qt.UserRole, customer["customer_id"])
                self.table.setItem(row, column, item)
            if customer["customer_id"] == selected_id:
                self.table.selectRow(row)
        if not customers:
            self.message.setText(self.t("cust_empty"))
            self.message.show()
        if conflicts:
            groups = "; ".join(", ".join(str(customer_id) for customer_id in group) for group in conflicts)
            self.conflict_message.setText(self.t("cust_email_conflicts").format(ids=groups))
            self.conflict_message.show()

    def open_editor(self, customer_id=None):
        try:
            dialog = CustomerDialog(self.translator, self.controller, customer_id, self)
        except CustomerValidationError:
            self.load_customers()
            self.message.setText(self.t("cust_error_not_found"))
            self.message.show()
            return
        except sqlite3.Error:
            self.message.setText(self.t("cust_error_storage"))
            self.message.show()
            return
        if dialog.exec() == QDialog.Accepted:
            self.load_customers(dialog.saved_customer_id)
        dialog.deleteLater()
