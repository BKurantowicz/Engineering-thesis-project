"""Editable transaction header, recipient, billing details and basket."""
import json
import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from controllers.sales_controller import priced_line


class OrderDialog(QDialog):
    def __init__(self, translator, sales, order_id=None, parent=None):
        super().__init__(parent)
        self.t, self.lang = translator.t, translator.lang_code
        self.sales, self.order_id = sales, order_id
        choices = sales.choices()
        self.products = choices["products"]
        self.customers = choices["customers"]
        self.types = choices["types"]
        self.setWindowTitle(self.t("sale_order"))
        self.resize(770,610)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        self.fields = {}
        menus = {
            "customer_id":[(f"{r['first_name']} {r['last_name']} · {r['customer_id']}",r["customer_id"]) for r in self.customers],
            "payment":[(r["name_"+self.lang],r["id"]) for r in choices["payments"]],
            "carrier":[(r["carrier_name"]+" · "+r["service_name_"+self.lang],r["shipping_id"]) for r in choices["carriers"]],
            "package_type":[(f"{r['package_code']} · {r['base_cost']:.2f} PLN",r["package_code"]) for r in self.types],
        }
        self.recipient_keys = ("first_name","last_name","street","postal_code","city","country","email","phone")
        self.billing_keys = ("billing_name","billing_street","billing_postal_code","billing_city","billing_country","tax_id")
        for title,keys in (("sale_order",("customer_id","channel","external_ref","payment","carrier","package_type","delivery","delivery_vat")),
                           ("recipient",self.recipient_keys),("billing",self.billing_keys)):
            page = QWidget()
            tabs.addTab(page,self.t(title))
            form = QFormLayout(page)
            for key in keys:
                if key in menus:
                    widget = QComboBox()
                    for label,value in menus[key]:
                        widget.addItem(label,value)
                else:
                    widget = QLineEdit()
                self.fields[key] = widget
                form.addRow(self.t(key,key),widget)
        self.fields["customer_id"].currentIndexChanged.connect(self.fill_customer)
        self.fields["package_type"].currentIndexChanged.connect(self.fill_charge)
        self.fill_customer()
        self.fill_charge()
        self.fields["delivery_vat"].setText("0")
        page = QWidget()
        tabs.addTab(page,self.t("basket"))
        form = QVBoxLayout(page)
        self.picker = QComboBox()
        self.picker.setEditable(True)
        self.picker.setInsertPolicy(QComboBox.NoInsert)
        for p in self.products:
            self.picker.addItem(f"{p['sku']} · {p['name_'+self.lang]}",p)
        self.picker.completer().setFilterMode(Qt.MatchContains)
        form.addWidget(self.picker)
        add = QPushButton(self.t("add_line"))
        add.clicked.connect(self.add_selected)
        form.addWidget(add)
        self.table = QTableWidget(0,4)
        self.table.setHorizontalHeaderLabels([self.t(k,k) for k in ("product","quantity","price","vat")])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        form.addWidget(self.table)
        remove = QPushButton(self.t("remove_line"))
        remove.clicked.connect(self.remove_selected)
        form.addWidget(remove)
        self.total = QLabel()
        self.error = QLabel()
        layout.addWidget(self.total)
        layout.addWidget(self.error)
        self.table.itemChanged.connect(self.recalculate)
        for key in ("delivery","delivery_vat"):
            self.fields[key].textChanged.connect(self.recalculate)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if order_id is not None:
            self.restore()
        self.recalculate()

    def fill_customer(self):
        idx = self.fields["customer_id"].currentIndex()
        if idx >= 0:
            for key in self.recipient_keys:
                self.fields[key].setText(self.customers[idx].get(key) or "")

    def fill_charge(self):
        idx = self.fields["package_type"].currentIndex()
        if idx >= 0:
            self.fields["delivery"].setText(str(self.types[idx]["base_cost"]))

    def add_selected(self):
        p = self.picker.currentData()
        if p and self.picker.currentText() == self.picker.itemText(self.picker.currentIndex()):
            self.add_line(p,1,p["price"],"")

    def remove_selected(self):
        if self.table.currentRow() >= 0:
            self.table.removeRow(self.table.currentRow())
            self.recalculate()

    def add_line(self,p,qty,unit,rate,item_id=None):
        row = self.table.rowCount()
        self.table.blockSignals(True)
        self.table.insertRow(row)
        for col,value in enumerate((p["sku"],qty,unit,rate)):
            cell = QTableWidgetItem(str(value))
            if col == 0:
                cell.setData(Qt.UserRole,p["product_id"])
                cell.setData(Qt.UserRole+1,item_id)
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row,col,cell)
        self.table.blockSignals(False)
        self.recalculate()

    def lines(self):
        return [dict(product_id=self.table.item(r,0).data(Qt.UserRole),item_id=self.table.item(r,0).data(Qt.UserRole+1),quantity=self.table.item(r,1).text(),
                     unit=self.table.item(r,2).text(),vat=self.table.item(r,3).text()) for r in range(self.table.rowCount())]

    def recalculate(self):
        try:
            prices = [priced_line(i["quantity"],i["unit"],i["vat"]) for i in self.lines()]
            prices.append(priced_line(1,self.fields["delivery"].text(),self.fields["delivery_vat"].text()))
            self.total.setText("   ·   ".join(f"{self.t(k)} {sum(i[k+'_cents'] for i in prices)/100:.2f} PLN"
                                              for k in ("net","vat","gross")))
        except ValueError:
            self.total.setText(self.t("enter_prices"))

    def restore(self):
        order, items = self.sales.details(self.order_id)
        data = json.loads(order["sales_snapshot"] or "{}")
        for field,value in (("customer_id",order["customer_id"]),("payment",order["payment_method_id"]),
                            ("carrier",data.get("carrier")),("package_type",data.get("package_type"))):
            self.fields[field].setCurrentIndex(self.fields[field].findData(value))
        for key,value in {**data,**data.get("recipient",{}),**data.get("billing",{})}.items():
            if isinstance(self.fields.get(key),QLineEdit):
                self.fields[key].setText(str(value or ""))
        for item in items:
            saved=json.loads(item["sale_snapshot"] or "{}")
            p = saved or next((p for p in self.products if p["product_id"]==item["product_id"]),None)
            if not p:
                raise ValueError("product")
            self.add_line(p,item["quantity"],item["unit_price"],saved.get("vat",""),item["item_id"])

    def save(self):
        fields = {k:(w.currentData() if isinstance(w,QComboBox) else w.text().strip()) for k,w in self.fields.items()}
        fields["recipient"] = {k:fields.pop(k) for k in self.recipient_keys}
        fields["billing"] = {k:fields.pop(k) for k in self.billing_keys}
        try:
            self.sales.save(fields,self.lines(),self.order_id)
        except (ValueError,sqlite3.Error) as exc:
            key = getattr(exc,"field",None) or str(exc)
            self.error.setText(self.t("invalid_value")+" · "+self.t(key,key))
            return
        self.accept()
