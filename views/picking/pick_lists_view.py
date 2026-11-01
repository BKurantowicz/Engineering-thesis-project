"""Saved pick-list execution and shortage history."""

import sqlite3

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton, QSpinBox, QStyledItemDelegate, QTableWidgetItem, QVBoxLayout, QWidget

from controllers.inventory_controller import WarehouseError
from controllers.shortage_controller import ShortageController
from views.picking.pick_dialogs import AllocationDialog, OrderSelectionDialog, ShortageDialog, table_widget
from views.products.product_dialog import warehouse_message


class PickListsView(QWidget):
    inventory_changed = Signal()

    def __init__(self, translator, controller):
        super().__init__()
        self.translator, self.controller = translator, controller
        self.t = translator.t
        self.shortages = ShortageController(controller.db_path)
        self.setObjectName("picking_view")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.current_list = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        title = QLabel(self.t("pick_title"))
        title.setObjectName("title_label")
        layout.addWidget(title)
        top = QHBoxLayout()
        self.generate_button = QPushButton(self.t("pick_generate"))
        self.generate_button.setObjectName("primary_btn")
        self.refresh_button = QPushButton(self.t("prod_refresh"))
        self.missing_button = QPushButton(self.t("pick_missing_history"))
        for button in (self.generate_button, self.refresh_button, self.missing_button):
            top.addWidget(button)
        top.addStretch()
        layout.addLayout(top)
        self.lists = QComboBox()
        self.lists.setItemDelegate(QStyledItemDelegate(self.lists))
        self.lists.setAccessibleName(self.t("pick_saved_lists"))
        layout.addWidget(self.lists)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.table = table_widget([self.t(key) for key in ("pick_order_id", "pick_product", "prod_location", "pick_allocated", "pick_picked", "prod_reserved", "pick_returned", "pick_line_state")])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        actions = QHBoxLayout()
        self.start_button = QPushButton(self.t("pick_start"))
        self.close_button = QPushButton(self.t("pick_close"))
        self.picked_total = QSpinBox()
        self.picked_total.setAccessibleName(self.t("pick_picked_total"))
        self.confirm_button = QPushButton(self.t("pick_confirm"))
        self.shortage_button = QPushButton(self.t("pick_report_shortage"))
        for widget in (self.start_button, self.close_button, QLabel(self.t("pick_picked_total")), self.picked_total, self.confirm_button, self.shortage_button):
            actions.addWidget(widget)
        layout.addLayout(actions)
        self.generate_button.clicked.connect(self.generate)
        self.refresh_button.clicked.connect(lambda: self.reload_lists(self.lists.currentData()))
        self.missing_button.clicked.connect(self.show_missing)
        self.lists.currentIndexChanged.connect(self.load_selected)
        self.table.itemSelectionChanged.connect(self.update_actions)
        self.start_button.clicked.connect(lambda: self.execute(self.controller.start_list, self.lists.currentData()))
        self.close_button.clicked.connect(lambda: self.execute(self.controller.close_list, self.lists.currentData()))
        self.confirm_button.clicked.connect(self.confirm_selected)
        self.shortage_button.clicked.connect(self.report_shortage)
        self.reload_lists()

    def show_error(self, error):
        self.message.setText(warehouse_message(self.translator, error) if isinstance(error, WarehouseError) else self.t("wh_error_storage"))
        self.message.show()

    def reload_lists(self, selected_id=None):
        self.lists.blockSignals(True)
        self.lists.clear()
        try:
            for row in self.controller.get_lists():
                self.lists.addItem(f"#{row['pick_list_id']} · {self.t('pick_status_' + row['status'], row['status'])} · {row['created_at']}", row["pick_list_id"])
        except sqlite3.Error as error:
            self.lists.blockSignals(False)
            self.current_list = None
            self.table.setRowCount(0)
            self.update_actions()
            self.show_error(error)
            return
        index = self.lists.findData(selected_id)
        self.lists.setCurrentIndex(max(index, 0) if self.lists.count() else -1)
        self.lists.blockSignals(False)
        self.load_selected()

    def load_selected(self):
        self.current_list = None
        self.table.setRowCount(0)
        self.message.hide()
        list_id = self.lists.currentData()
        if list_id is None:
            self.message.setText(self.t("pick_empty"))
            self.message.show()
            self.update_actions()
            return
        try:
            self.current_list = self.controller.get_list(list_id)
        except (WarehouseError, sqlite3.Error) as error:
            self.show_error(error)
            self.update_actions()
            return
        self.table.setRowCount(len(self.current_list["lines"]))
        for row, line in enumerate(self.current_list["lines"]):
            state = "cancelled" if line["order_status"] == "CANCELLED" else ("resolved" if line["cancelled"] else ("picked" if line["picked_quantity"] == line["quantity"] else "open"))
            values = (line["order_id"], line["sku"] + " — " + line["name_" + self.translator.lang_code], line["location_code"], line["quantity"], line["picked_quantity"], line["reserved_quantity"], line["returned_quantity"], self.t("pick_line_" + state))
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(Qt.UserRole, line)
                self.table.setItem(row, column, item)
        self.update_actions()

    def selected_line(self):
        item = self.table.item(self.table.currentRow(), 0)
        return item.data(Qt.UserRole) if item else None

    def update_actions(self):
        status = self.current_list["status"] if self.current_list else None
        line = self.selected_line()
        self.start_button.setEnabled(status == "PENDING")
        self.close_button.setEnabled(status in ("PENDING", "IN_PROGRESS"))
        can_pick = bool(line and status == "IN_PROGRESS" and not line["cancelled"] and line["reserved_quantity"])
        self.confirm_button.setEnabled(can_pick)
        self.picked_total.setEnabled(can_pick)
        self.shortage_button.setEnabled(bool(line and status in ("PENDING", "IN_PROGRESS")))
        if line:
            self.picked_total.setRange(line["picked_quantity"], min(line["quantity"], 2_147_483_647))
            self.picked_total.setValue(line["picked_quantity"])

    def execute(self, operation, *args):
        try:
            operation(*args)
        except (WarehouseError, sqlite3.Error) as error:
            self.show_error(error)
            return
        self.reload_lists(self.lists.currentData())
        self.inventory_changed.emit()

    def confirm_selected(self):
        line = self.selected_line()
        if line:
            self.execute(self.controller.confirm_pick, line["allocation_id"], self.picked_total.value())

    def generate(self):
        try:
            selection = OrderSelectionDialog(self.translator, self.controller, self)
            accepted = selection.exec() == QDialog.Accepted
            order_ids = selection.selected_order_ids
            selection.deleteLater()
            if not accepted:
                return
            allocation = AllocationDialog(self.translator, self.controller, order_ids, self)
        except (WarehouseError, sqlite3.Error) as error:
            self.show_error(error)
            return
        if allocation.exec() == QDialog.Accepted:
            self.reload_lists(allocation.saved_list_id)
            self.inventory_changed.emit()
        allocation.deleteLater()

    def report_shortage(self):
        line = self.selected_line()
        if not line:
            return
        try:
            dialog = ShortageDialog(self.translator, self.controller, self.shortages, line, self)
        except (WarehouseError, sqlite3.Error) as error:
            self.show_error(error)
            return
        if dialog.exec() == QDialog.Accepted:
            result = dialog.saved_result
            self.reload_lists(line["pick_list_id"])
            self.inventory_changed.emit()
            numbers = lambda key: ", ".join(map(str, result[key])) or self.t("pick_none")
            self.message.setText(self.t("pick_shortage_result").format(fulfilled=numbers("fulfilled"), cancelled=numbers("cancelled"), lists=numbers("affected_lists")))
            self.message.show()
        dialog.deleteLater()

    def show_missing(self):
        try:
            records = self.controller.get_missing_stock()
        except sqlite3.Error as error:
            self.show_error(error)
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(self.t("pick_missing_history"))
        dialog.resize(1000, 500)
        layout = QVBoxLayout(dialog)
        table = table_widget([self.t(key) for key in ("prod_sku", "pick_missing_quantity", "prod_location", "pick_list_id", "pick_operation", "pick_date")])
        table.setRowCount(len(records))
        for row, record in enumerate(records):
            for column, key in enumerate(("sku", "missing_quantity", "location_code", "pick_list_id", "operation_id", "created_at")):
                table.setItem(row, column, QTableWidgetItem(str(record[key])))
        layout.addWidget(table)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText(self.t("pick_dismiss"))
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()
        dialog.deleteLater()
