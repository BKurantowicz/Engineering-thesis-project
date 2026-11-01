"""Customer list providing reachable Add/Edit master-data forms."""

import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from controllers.customer_controller import CustomerValidationError
from views.customers.customer_dialog import CustomerDialog


class CustomersView(QWidget):
    COLUMNS = ("customer_id", "first_name", "last_name", "email", "phone", "city", "is_active")

    def __init__(self, translator, controller):
        super().__init__()
        self.setObjectName("customers_view")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.translator = translator
        self.t = translator.t
        self.controller = controller
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        title = QLabel(self.t("cust_title"))
        title.setObjectName("title_label")
        layout.addWidget(title)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(self.t("cust_search_hint"))
        self.search_input.setAccessibleName(self.t("cust_search_hint"))
        self.search_input.setClearButtonEnabled(True)
        layout.addWidget(self.search_input)
        actions = QHBoxLayout()
        self.add_button = QPushButton(self.t("cust_add"))
        self.add_button.setObjectName("primary_btn")
        self.edit_button = QPushButton(self.t("cust_edit"))
        self.active_button = QPushButton(self.t("cust_deactivate"))
        self.delete_button = QPushButton(self.t("cust_delete"))
        self.delete_button.setObjectName("danger_btn")
        for button in (self.edit_button, self.active_button, self.delete_button):
            button.setEnabled(False)
        self.add_button.clicked.connect(lambda: self.open_editor())
        self.edit_button.clicked.connect(lambda: self.open_editor(self.selected_customer_id()))
        self.active_button.clicked.connect(self.toggle_active)
        self.delete_button.clicked.connect(self.delete_selected)
        actions.addWidget(self.add_button)
        actions.addWidget(self.edit_button)
        actions.addWidget(self.active_button)
        actions.addWidget(self.delete_button)
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
        self.table.itemSelectionChanged.connect(self.update_actions)
        layout.addWidget(self.table)
        self.search_input.textChanged.connect(lambda: self.load_customers())
        self.load_customers()

    def selected_customer_id(self):
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        return item.data(Qt.UserRole) if item else None

    def update_actions(self):
        customer_id = self.selected_customer_id()
        for button in (self.edit_button, self.active_button, self.delete_button):
            button.setEnabled(customer_id is not None)
        if customer_id is not None:
            active = bool(self.table.item(self.table.currentRow(), 0).data(Qt.UserRole + 1))
            self.active_button.setText(self.t("cust_deactivate" if active else "cust_reactivate"))

    def show_action_error(self, error):
        self.load_customers()
        code = error.code if isinstance(error, CustomerValidationError) else "storage"
        self.message.setText(self.t("cust_error_" + code))
        self.message.show()

    def toggle_active(self):
        customer_id = self.selected_customer_id()
        if customer_id is None:
            return
        active = bool(self.table.item(self.table.currentRow(), 0).data(Qt.UserRole + 1))
        try:
            self.controller.set_active(customer_id, not active)
        except (CustomerValidationError, sqlite3.Error) as error:
            self.show_action_error(error)
            return
        self.load_customers(customer_id)

    def confirm_delete(self, customer_id):
        prompt = QMessageBox(self)
        prompt.setWindowTitle(self.t("cust_delete"))
        prompt.setIcon(QMessageBox.Question)
        prompt.setText(self.t("cust_confirm_delete").format(id=customer_id))
        prompt.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        prompt.setDefaultButton(QMessageBox.No)
        prompt.button(QMessageBox.Yes).setText(self.t("cust_delete"))
        prompt.button(QMessageBox.No).setText(self.t("cust_cancel"))
        accepted = prompt.exec() == QMessageBox.Yes
        prompt.deleteLater()
        return accepted

    def delete_selected(self):
        customer_id = self.selected_customer_id()
        if customer_id is None or not self.confirm_delete(customer_id):
            return
        try:
            self.controller.delete_customer(customer_id)
        except (CustomerValidationError, sqlite3.Error) as error:
            self.show_action_error(error)
            return
        self.load_customers()

    def load_customers(self, selected_id=None):
        self.table.setRowCount(0)
        self.message.clear()
        self.message.hide()
        self.conflict_message.clear()
        self.conflict_message.hide()
        try:
            customers = self.controller.get_customers(self.search_input.text())
            conflicts = self.controller.get_email_conflicts()
        except sqlite3.Error:
            self.message.setText(self.t("cust_error_storage"))
            self.message.show()
            return
        self.table.setRowCount(len(customers))
        for row, customer in enumerate(customers):
            for column, field in enumerate(self.COLUMNS):
                text = self.t("cust_active" if customer[field] else "cust_inactive") if field == "is_active" else ("" if customer[field] is None else str(customer[field]))
                item = QTableWidgetItem(text)
                if column == 0:
                    item.setData(Qt.UserRole, customer["customer_id"])
                    item.setData(Qt.UserRole + 1, bool(customer["is_active"]))
                self.table.setItem(row, column, item)
            if customer["customer_id"] == selected_id:
                self.table.selectRow(row)
        if not customers:
            self.message.setText(self.t("cust_no_matches" if self.search_input.text().strip() else "cust_empty"))
            self.message.show()
        if conflicts:
            groups = "; ".join(", ".join(str(customer_id) for customer_id in group) for group in conflicts)
            self.conflict_message.setText(self.t("cust_email_conflicts").format(ids=groups))
            self.conflict_message.show()
        self.update_actions()

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
