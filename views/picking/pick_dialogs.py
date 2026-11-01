"""Explicit order selection, rack allocations, and physical shortage counts."""

import sqlite3
import uuid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QDialog, QDialogButtonBox, QHeaderView, QLabel, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout

from controllers.inventory_controller import WarehouseError
from views.products.product_dialog import warehouse_message


def table_widget(headers, parent=None):
    table = QTableWidget(0, len(headers), parent)
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    return table


class PickDialog(QDialog):
    def __init__(self, translator, title_key, parent=None):
        super().__init__(parent)
        self.translator = translator
        self.t = translator.t
        self.setWindowTitle(self.t(title_key))
        self.layout = QVBoxLayout(self)
        self.error_label = QLabel()
        self.error_label.setObjectName("error_label")
        self.error_label.setWordWrap(True)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText(self.t(title_key))
        self.buttons.button(QDialogButtonBox.Cancel).setText(self.t("prod_cancel"))
        self.buttons.rejected.connect(self.reject)

    def finish_layout(self):
        self.layout.addWidget(self.error_label)
        self.layout.addWidget(self.buttons)

    def show_error(self, error):
        self.error_label.setText(warehouse_message(self.translator, error) if isinstance(error, WarehouseError) else self.t("wh_error_storage"))


class OrderSelectionDialog(PickDialog):
    def __init__(self, translator, controller, parent=None):
        super().__init__(translator, "pick_select_orders", parent)
        self.resize(720, 450)
        self.selected_order_ids = []
        hint = QLabel(self.t("pick_selection_hint"))
        hint.setWordWrap(True)
        self.layout.addWidget(hint)
        self.table = table_widget([self.t("pick_order_id"), self.t("pick_date"), self.t("pick_status")])
        self.table.setSelectionMode(QAbstractItemView.MultiSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        orders = controller.get_eligible_orders()
        self.table.setRowCount(len(orders))
        for row, order in enumerate(orders):
            for column, text in enumerate((str(order["order_id"]), order["order_date"], self.t("pick_status_" + order["status_code"]))):
                item = QTableWidgetItem(text)
                if column == 0:
                    item.setData(Qt.UserRole, order["order_id"])
                self.table.setItem(row, column, item)
        self.layout.addWidget(self.table)
        self.finish_layout()
        self.buttons.accepted.connect(self.choose)
        if not orders:
            self.error_label.setText(self.t("pick_no_eligible"))

    def choose(self):
        self.selected_order_ids = [self.table.item(index.row(), 0).data(Qt.UserRole) for index in self.table.selectionModel().selectedRows()]
        if not self.selected_order_ids:
            self.show_error(WarehouseError("select_orders"))
            return
        self.accept()


class AllocationDialog(PickDialog):
    def __init__(self, translator, controller, order_ids, parent=None):
        super().__init__(translator, "pick_generate", parent)
        self.controller, self.order_ids = controller, order_ids
        self.saved_list_id = None
        self.resize(1000, 600)
        hint = QLabel(self.t("pick_allocation_hint"))
        hint.setWordWrap(True)
        self.layout.addWidget(hint)
        self.table = table_widget([self.t(key) for key in ("pick_order_id", "prod_sku", "pick_product", "pick_required", "prod_location", "pick_available", "pick_allocate")])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.editors = []
        for item in controller.allocation_options(order_ids):
            sources = item["sources"] or [{"location_id": None, "location_code": self.t("pick_no_source"), "available": 0}]
            for source in sources:
                row = self.table.rowCount()
                self.table.insertRow(row)
                for column, value in enumerate((item["order_id"], item["sku"], item["name_" + translator.lang_code], item["quantity"], source["location_code"], source["available"])):
                    self.table.setItem(row, column, QTableWidgetItem(str(value)))
                quantity = QSpinBox()
                quantity.setRange(0, min(source["available"], item["quantity"], 2_147_483_647))
                quantity.setAccessibleName(f"{item['order_id']} / {item['sku']} / {source['location_code']}")
                self.table.setCellWidget(row, 6, quantity)
                self.editors.append((item["item_id"], source["location_id"], quantity))
        self.table.resizeRowsToContents()
        self.layout.addWidget(self.table)
        self.finish_layout()
        self.buttons.accepted.connect(self.save)

    def save(self):
        if self.saved_list_id is not None:
            return
        allocations = [dict(order_item_id=item_id, location_id=location_id, quantity=editor.value()) for item_id, location_id, editor in self.editors if editor.value()]
        try:
            self.saved_list_id = self.controller.create_list(self.order_ids, allocations)
        except (WarehouseError, sqlite3.Error) as error:
            self.show_error(error)
            return
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        self.accept()


class ShortageDialog(PickDialog):
    def __init__(self, translator, picking, shortages, line, parent=None):
        super().__init__(translator, "pick_report_shortage", parent)
        self.shortages, self.line = shortages, line
        self.operation_id = str(uuid.uuid4())
        self.saved_result = None
        self.resize(600, 300)
        recorded = picking.get_rack_quantity(line["product_id"], line["location_id"])
        self.recorded_quantity = recorded
        hint = QLabel(self.t("pick_count_hint").format(sku=line["sku"], rack=line["location_code"], recorded=recorded))
        hint.setWordWrap(True)
        self.layout.addWidget(hint)
        self.actual = QSpinBox()
        self.actual.setRange(0, min(recorded, 2_147_483_647))
        self.actual.setValue(min(recorded, 2_147_483_647))
        self.actual.setAccessibleName(self.t("pick_actual_quantity"))
        self.layout.addWidget(self.actual)
        self.finish_layout()
        self.buttons.accepted.connect(self.save)

    def save(self):
        if self.saved_result is not None:
            return
        try:
            self.saved_result = self.shortages.reconcile(self.line["pick_list_id"], self.line["product_id"], self.line["location_id"], self.actual.value(), self.operation_id, self.recorded_quantity)
        except (WarehouseError, sqlite3.Error) as error:
            self.show_error(error)
            return
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        self.accept()
