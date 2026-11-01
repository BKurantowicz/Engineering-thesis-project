"""Searchable catalogue with explicit, capacity-checked inventory additions."""

import sqlite3

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QComboBox, QDialog, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QStyledItemDelegate, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from controllers.inventory_controller import WarehouseError
from views.products.product_dialog import ProductDialog, StockDialog, warehouse_message


class ProductsView(QWidget):
    stock_changed = Signal()

    def __init__(self, translator, controller):
        super().__init__()
        self.translator, self.controller = translator, controller
        self.t = translator.t
        self.setObjectName("products_view")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.columns = ("product_id", "sku", "name_" + translator.lang_code, "price", "physical", "reserved", "available", "locations", "is_active")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        title = QLabel(self.t("prod_title"))
        title.setObjectName("title_label")
        layout.addWidget(title)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(self.t("prod_search_hint"))
        self.search_input.setAccessibleName(self.t("prod_search_hint"))
        self.search_input.setClearButtonEnabled(True)
        layout.addWidget(self.search_input)
        filters = QGridLayout()
        self.location = QComboBox()
        self.location.setItemDelegate(QStyledItemDelegate(self.location))
        self.location.addItem(self.t("prod_warehouse"), None)
        for rack in controller.inventory.get_locations():
            self.location.addItem(rack["location_code"], rack["location_id"])
        filters.addWidget(QLabel(self.t("prod_location")), 0, 0)
        filters.addWidget(self.location, 1, 0)
        self.bounds = {}
        for column, field in enumerate(("min_quantity", "max_quantity", "min_price", "max_price"), 1):
            editor = QLineEdit()
            editor.setPlaceholderText(self.t("prod_unrestricted"))
            editor.setAccessibleName(self.t("prod_" + field))
            self.bounds[field] = editor
            filters.addWidget(QLabel(self.t("prod_" + field)), 0, column)
            filters.addWidget(editor, 1, column)
        layout.addLayout(filters)
        actions = QHBoxLayout()
        self.buttons = {}
        for key in ("add", "edit", "add_stock", "deactivate", "delete", "refresh"):
            button = QPushButton(self.t("prod_" + key))
            self.buttons[key] = button
            actions.addWidget(button)
        self.buttons["add"].setObjectName("primary_btn")
        self.buttons["delete"].setObjectName("danger_btn")
        actions.addStretch()
        layout.addLayout(actions)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.conflicts = QLabel()
        self.conflicts.setObjectName("error_label")
        self.conflicts.setWordWrap(True)
        layout.addWidget(self.conflicts)
        self.table = QTableWidget(0, len(self.columns))
        self.table.setHorizontalHeaderLabels([self.t("prod_" + field) for field in self.columns])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table)
        self.buttons["add"].clicked.connect(lambda: self.open_editor())
        self.buttons["edit"].clicked.connect(lambda: self.open_editor(self.selected_id()))
        self.buttons["add_stock"].clicked.connect(self.open_stock)
        self.buttons["deactivate"].clicked.connect(self.toggle_active)
        self.buttons["delete"].clicked.connect(self.delete_selected)
        self.buttons["refresh"].clicked.connect(lambda: self.load_products(self.selected_id()))
        self.search_input.textChanged.connect(lambda: self.load_products())
        self.location.currentIndexChanged.connect(lambda: self.load_products())
        for editor in self.bounds.values():
            editor.textChanged.connect(lambda: self.load_products())
        self.table.itemSelectionChanged.connect(self.update_actions)
        self.load_products()

    def selected_id(self):
        item = self.table.item(self.table.currentRow(), 0)
        return item.data(Qt.UserRole) if item else None

    def update_actions(self):
        product_id = self.selected_id()
        for key in ("edit", "add_stock", "deactivate", "delete"):
            self.buttons[key].setEnabled(product_id is not None)
        if product_id is not None:
            active = self.table.item(self.table.currentRow(), 0).data(Qt.UserRole + 1)
            self.buttons["deactivate"].setText(self.t("prod_deactivate" if active else "prod_reactivate"))

    def show_error(self, error):
        self.message.setText(warehouse_message(self.translator, error) if isinstance(error, WarehouseError) else self.t("wh_error_storage"))
        self.message.show()

    def load_products(self, selected_id=None):
        self.table.setRowCount(0)
        self.message.hide()
        self.conflicts.hide()
        try:
            products = self.controller.get_products(self.search_input.text(), self.location.currentData(), **{key: editor.text() for key, editor in self.bounds.items()})
            conflicts = self.controller.get_sku_conflicts()
        except (WarehouseError, sqlite3.Error) as error:
            self.show_error(error)
            self.update_actions()
            return
        self.table.setRowCount(len(products))
        for row, product in enumerate(products):
            for column, field in enumerate(self.columns):
                value = self.t("prod_active" if product[field] else "prod_inactive") if field == "is_active" else (f"{product[field]:.2f}" if field == "price" else str(product[field]))
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.UserRole, product["product_id"])
                    item.setData(Qt.UserRole + 1, bool(product["is_active"]))
                self.table.setItem(row, column, item)
            if product["product_id"] == selected_id:
                self.table.selectRow(row)
        if not products:
            filtered = self.search_input.text().strip() or self.location.currentData() is not None or any(editor.text().strip() for editor in self.bounds.values())
            self.message.setText(self.t("prod_no_matches" if filtered else "prod_empty"))
            self.message.show()
        if conflicts:
            self.conflicts.setText(self.t("prod_sku_conflicts").format(ids="; ".join(", ".join(map(str, ids)) for ids in conflicts)))
            self.conflicts.show()
        self.update_actions()

    def open_editor(self, product_id=None):
        try:
            dialog = ProductDialog(self.translator, self.controller, product_id, self)
        except (WarehouseError, sqlite3.Error) as error:
            self.show_error(error)
            return
        if dialog.exec() == QDialog.Accepted:
            self.load_products(dialog.saved_product_id)
            self.stock_changed.emit()
        dialog.deleteLater()

    def open_stock(self):
        product_id = self.selected_id()
        if product_id is None:
            return
        try:
            dialog = StockDialog(self.translator, self.controller, product_id, self)
        except (WarehouseError, sqlite3.Error) as error:
            self.show_error(error)
            return
        if dialog.exec() == QDialog.Accepted:
            self.load_products(product_id)
            self.stock_changed.emit()
        dialog.deleteLater()

    def toggle_active(self):
        product_id = self.selected_id()
        if product_id is None:
            return
        active = bool(self.table.item(self.table.currentRow(), 0).data(Qt.UserRole + 1))
        try:
            self.controller.set_active(product_id, not active)
        except (WarehouseError, sqlite3.Error) as error:
            self.show_error(error)
            return
        self.load_products(product_id)

    def delete_selected(self):
        product_id = self.selected_id()
        if product_id is None:
            return
        prompt = QMessageBox(self)
        prompt.setWindowTitle(self.t("prod_delete"))
        prompt.setText(self.t("prod_confirm_delete").format(id=product_id))
        prompt.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        prompt.setDefaultButton(QMessageBox.No)
        prompt.button(QMessageBox.Yes).setText(self.t("prod_delete"))
        prompt.button(QMessageBox.No).setText(self.t("prod_cancel"))
        accepted = prompt.exec() == QMessageBox.Yes
        prompt.deleteLater()
        if not accepted:
            return
        try:
            self.controller.delete_product(product_id)
        except (WarehouseError, sqlite3.Error) as error:
            self.show_error(error)
            return
        self.load_products()
