"""Shop names, shared warehouses and employee memberships."""
import sqlite3
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
    QWidget, QComboBox, QPushButton, QListWidget, QListWidgetItem, QInputDialog,
    QCheckBox, QLabel, QMessageBox, QDialogButtonBox)
from controllers.shop_controller import ShopController


class ShopAdminDialog(QDialog):
    def __init__(self, auth, translator, parent=None):
        super().__init__(parent)
        auth.require(True)
        self.auth, self.t = auth, translator.t
        self.ctrl = ShopController(auth)
        self.setWindowTitle(self.t('shop_manage'))
        self.resize(620,520)
        root = QVBoxLayout(self)
        tabs = QTabWidget()
        root.addWidget(tabs)
        shops = QWidget()
        layout = QVBoxLayout(shops)
        tabs.addTab(shops,self.t('shop_warehouses'))
        self.shops = QComboBox()
        layout.addWidget(self.shops)
        row = QHBoxLayout()
        layout.addLayout(row)
        self.button(row,'shop_create',lambda: self.name_shop(False))
        self.button(row,'shop_rename',lambda: self.name_shop(True))
        layout.addWidget(QLabel(self.t('shop_warehouse_hint')))
        self.warehouses = QListWidget()
        layout.addWidget(self.warehouses)
        row = QHBoxLayout()
        layout.addLayout(row)
        self.button(row,'warehouse_create',self.create_warehouse)
        self.button(row,'shop_save_warehouses',self.save_warehouses)
        employees = QWidget()
        layout = QVBoxLayout(employees)
        tabs.addTab(employees,self.t('shop_employee_access'))
        self.employees = QComboBox()
        for employee in auth.employees():
            self.employees.addItem(employee['login'],employee['user_id'])
        layout.addWidget(self.employees)
        self.all_shops = QCheckBox(self.t('shop_all_future'))
        layout.addWidget(self.all_shops)
        self.memberships = QListWidget()
        layout.addWidget(self.memberships)
        self.button(layout,'shop_save_access',self.save_employee)
        self.shops.currentIndexChanged.connect(lambda: self.guarded(self.load_warehouses))
        self.employees.currentIndexChanged.connect(lambda: self.guarded(self.load_employee))
        self.all_shops.toggled.connect(lambda checked: self.memberships.setEnabled(not checked))
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.button(QDialogButtonBox.Close).setText(self.t('shop_close'))
        close.rejected.connect(self.accept)
        root.addWidget(close)
        self.reload()

    def button(self, layout, key, method):
        button = QPushButton(self.t(key))
        button.clicked.connect(lambda: self.guarded(method))
        layout.addWidget(button)

    def guarded(self, method):
        try:
            method()
        except (ValueError,sqlite3.Error) as error:
            QMessageBox.warning(self,self.t('operation_failed'),self.t(str(error),self.t('operation_failed')))

    @staticmethod
    def checklist(widget, records, key, checked):
        widget.clear()
        for record in records:
            item = QListWidgetItem(record['name'])
            item.setData(Qt.UserRole,record[key])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if record[key] in checked else Qt.Unchecked)
            widget.addItem(item)

    @staticmethod
    def selected(widget):
        return [widget.item(i).data(Qt.UserRole) for i in range(widget.count())
                if widget.item(i).checkState() == Qt.Checked]

    def reload(self, shop_id=None):
        selected = shop_id or self.shops.currentData()
        self.shops.blockSignals(True)
        self.shops.clear()
        for shop in self.ctrl.shops():
            self.shops.addItem(shop['name'],shop['shop_id'])
        self.shops.setCurrentIndex(max(0,self.shops.findData(selected)))
        self.shops.blockSignals(False)
        self.load_warehouses()
        self.load_employee()

    def load_warehouses(self):
        sid = self.shops.currentData()
        assigned = {w['warehouse_id'] for w in self.ctrl.warehouses(sid)} if sid else set()
        self.checklist(self.warehouses,self.ctrl.warehouses(),'warehouse_id',assigned)

    def name_shop(self, rename):
        name, ok = QInputDialog.getText(self,self.t('shop_rename' if rename else 'shop_create'),
            self.t('shop_name'),text=self.shops.currentText() if rename else '')
        if ok:
            sid = self.ctrl.save_shop(name,self.shops.currentData() if rename else None)
            self.reload(sid)

    def create_warehouse(self):
        name, ok = QInputDialog.getText(self,self.t('warehouse_create'),self.t('warehouse_name'))
        if ok:
            self.ctrl.create_warehouse(name)
            self.load_warehouses()

    def save_warehouses(self):
        self.ctrl.assign_warehouses(self.shops.currentData(),self.selected(self.warehouses))
        self.load_warehouses()

    def load_employee(self):
        uid = self.employees.currentData()
        all_shops, assigned = self.ctrl.assignments(uid) if uid else (False,[])
        self.all_shops.setChecked(all_shops)
        self.checklist(self.memberships,self.ctrl.shops(),'shop_id',assigned)
        self.memberships.setEnabled(bool(uid) and not all_shops)

    def save_employee(self):
        self.ctrl.assign_employee(self.employees.currentData(),self.selected(self.memberships),all_shops=self.all_shops.isChecked())
        self.load_employee()
