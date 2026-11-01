"""Catalogue and explicit stock-entry dialogs using controller validation."""

import sqlite3

from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QSpinBox, QStyledItemDelegate, QVBoxLayout

from controllers.inventory_controller import WarehouseError


def warehouse_message(translator, error):
    details = dict(error.details)
    details["field"] = translator.t("prod_" + details.get("field", ""))
    details["constraints"] = ", ".join(translator.t("cap_" + value) for value in details.get("constraints", []))
    message = translator.t("wh_error_" + error.code, str(error)).format(**details)
    if "alternatives" in details:
        alternatives = details["alternatives"]
        message += " " + (translator.t("wh_alternatives").format(racks=", ".join(alternatives)) if alternatives else translator.t("wh_no_alternatives"))
    return message


class ProductDialog(QDialog):
    def __init__(self, translator, controller, product_id=None, parent=None):
        super().__init__(parent)
        self.translator, self.controller, self.product_id = translator, controller, product_id
        self.saved_product_id = None
        self.setWindowTitle(translator.t("prod_edit" if product_id is not None else "prod_add"))
        self.resize(560, 560)
        layout = QVBoxLayout(self)
        hint = QLabel(translator.t("prod_form_hint"))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        form = QFormLayout()
        self.fields = {}
        for field in controller.FIELDS:
            editor = QLineEdit()
            editor.setObjectName("product_" + field)
            form.addRow(translator.t("prod_" + field), editor)
            self.fields[field] = editor
        layout.addLayout(form)
        self.error_label = QLabel()
        self.error_label.setObjectName("error_label")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText(translator.t("prod_save"))
        self.buttons.button(QDialogButtonBox.Cancel).setText(translator.t("prod_cancel"))
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        if product_id is not None:
            product = controller.get_product(product_id)
            for field, editor in self.fields.items():
                editor.setText("" if product[field] is None else str(product[field]))

    def save(self):
        if self.saved_product_id is not None:
            return
        try:
            self.saved_product_id = self.controller.save_product({field: editor.text() for field, editor in self.fields.items()}, self.product_id)
        except WarehouseError as error:
            self.error_label.setText(warehouse_message(self.translator, error))
            field = error.details.get("field")
            if field in self.fields:
                self.fields[field].setFocus()
            return
        except sqlite3.Error:
            self.error_label.setText(self.translator.t("wh_error_storage"))
            return
        self.buttons.button(QDialogButtonBox.Save).setEnabled(False)
        self.accept()


class StockDialog(QDialog):
    def __init__(self, translator, controller, product_id, parent=None):
        super().__init__(parent)
        self.translator, self.controller, self.product_id = translator, controller, product_id
        self.saved = False
        self.setWindowTitle(translator.t("prod_add_stock"))
        self.resize(520, 260)
        layout = QVBoxLayout(self)
        product = controller.get_product(product_id)
        layout.addWidget(QLabel(product["sku"] + " — " + product["name_" + translator.lang_code]))
        form = QFormLayout()
        self.location = QComboBox()
        self.location.setItemDelegate(QStyledItemDelegate(self.location))
        for rack in controller.inventory.get_locations():
            self.location.addItem(rack["location_code"], rack["location_id"])
        self.quantity = QSpinBox()
        self.quantity.setRange(1, 2_147_483_647)
        form.addRow(translator.t("prod_location"), self.location)
        form.addRow(translator.t("prod_quantity"), self.quantity)
        layout.addLayout(form)
        self.error_label = QLabel()
        self.error_label.setObjectName("error_label")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText(translator.t("prod_add_stock"))
        self.buttons.button(QDialogButtonBox.Cancel).setText(translator.t("prod_cancel"))
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def save(self):
        if self.saved:
            return
        try:
            self.controller.inventory.add_stock(self.product_id, self.location.currentData(), self.quantity.value())
        except WarehouseError as error:
            self.error_label.setText(warehouse_message(self.translator, error))
            return
        except sqlite3.Error:
            self.error_label.setText(self.translator.t("wh_error_storage"))
            return
        self.saved = True
        self.buttons.button(QDialogButtonBox.Save).setEnabled(False)
        self.accept()
