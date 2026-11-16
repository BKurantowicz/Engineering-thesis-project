"""Warehouse administration, stock movements, receipt preview and audit lookup."""
import csv
import sqlite3
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QComboBox, QLineEdit, QPushButton, QLabel, QTabWidget, QSpinBox, QTableWidget,
    QTableWidgetItem, QFileDialog, QMessageBox, QHeaderView, QAbstractItemView)
from controllers.warehouse_controller import WarehouseController
from controllers.product_controller import ProductController
from controllers.auth_controller import AuthError


class WarehouseView(QWidget):
    changed = Signal()

    def __init__(self, translator, db_path, auth):
        super().__init__()
        self.t, self.lang, self.auth = translator.t, translator.lang_code, auth
        self.ctrl = WarehouseController(db_path)
        self.products = ProductController(db_path)
        self.preview_rows = None
        self.preview_number = None
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.racks = QComboBox()
        self.product = QComboBox()
        self.source = QComboBox()
        self.target = QComboBox()
        self.quantity = QSpinBox()
        self.quantity.setRange(1, 2147483647)
        self.reason = QLineEdit()
        page, form = self.page('warehouse_stock')
        for key, control in (('product',self.product),('source_rack',self.source),('target_rack',self.target),
                             ('quantity',self.quantity),('operation_reason',self.reason)):
            form.addRow(self.t(key), control)
        for key, method in (('stock_receipt',self.receipt),('stock_withdraw',self.withdraw),('stock_transfer',self.transfer)):
            self.button(form, key, method)
        page, form = self.page('warehouse_racks')
        self.code, self.weight, self.volume = QLineEdit(), QLineEdit(), QLineEdit()
        for key, control in (('rack_code',self.code),('rack_weight',self.weight),('rack_volume',self.volume)):
            form.addRow(self.t(key), control)
        create = self.button(form, 'rack_create', self.create_rack)
        form.addRow(self.t('source_rack'), self.racks)
        archive = self.button(form, 'rack_archive', self.archive)
        admin = auth.require()['role'] == 'admin'
        for widget in (create,archive,self.code,self.weight,self.volume):
            widget.setEnabled(admin)
            if not admin:
                widget.setToolTip(self.t('auth_forbidden'))
        page, form = self.page('delivery_import')
        hint = QLabel(self.t('delivery_schema'))
        hint.setWordWrap(True)
        form.addRow(hint)
        self.delivery_number = QLineEdit()
        self.delivery_number.textChanged.connect(self.invalidate_preview)
        form.addRow(self.t('delivery_number'), self.delivery_number)
        self.button(form, 'delivery_preview', self.preview)
        self.button(form, 'delivery_example', self.example)
        self.preview_table = self.table(('row_number','tbl_sku','tbl_name','source_rack','quantity','state'))
        form.addRow(self.preview_table)
        self.commit_button = self.button(form, 'delivery_commit', self.commit)
        self.commit_button.setEnabled(False)
        page, form = self.page('operation_history')
        self.filters = {}
        for key in ('since','until','operation','sku','rack'):
            if key == 'operation':
                field = QComboBox()
                field.addItem(self.t('all_operations'), '')
                for code in ('WAREHOUSE_CREATE','WAREHOUSE_REGISTER','RACK_CREATE','RACK_ARCHIVE','RECEIPT',
                             'WITHDRAWAL','TRANSFER_OUT','TRANSFER_IN','CSV_RECEIPT','PICK','SHORTAGE','MISSING','RETURN'):
                    field.addItem(self.t('operation_'+code,code),code)
            else:
                field = QLineEdit()
                field.setPlaceholderText('YYYY-MM-DD' if key in ('since','until') else self.t('filter_' + key))
            form.addRow(self.t('filter_' + key), field)
            self.filters[key] = field
        self.button(form, 'prod_refresh', self.reload_history)
        self.history_table = self.table(('event_time','operation_type','tbl_sku','source_rack','quantity','actor','operation_id','details'))
        form.addRow(self.history_table)
        self.empty = QLabel(self.t('history_empty'))
        form.addRow(self.empty)
        self.tabs.currentChanged.connect(lambda: self.guarded(self.reload))
        self.reload()

    def page(self, key):
        widget = QWidget()
        self.tabs.addTab(widget, self.t(key))
        return widget, QFormLayout(widget)

    def table(self, keys):
        table = QTableWidget(0,len(keys))
        table.setHorizontalHeaderLabels([self.t(k,k) for k in keys])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        table.horizontalHeader().setStretchLastSection(True)
        table.resizeColumnsToContents()
        return table

    def button(self, form, key, method):
        button = QPushButton(self.t(key,key))
        button.clicked.connect(lambda: self.guarded(method))
        form.addRow(button)
        return button

    def guarded(self, method):
        self.message.clear()
        try:
            method()
        except (ValueError, sqlite3.Error, OSError) as error:
            details = getattr(error, 'details', {})
            text = self.t(str(error), self.t('operation_failed'))
            if 'row' in details:
                text = f"{self.t('row_number')} {details['row']}: {text}"
            if 'stock' in details:
                text += f" / {self.t('quantity')}: {details['stock']} / {self.t('prod_reserved')}: {details['reserved']}"
            if 'alternatives' in details:
                text += ' ' + (self.t('wh_alternatives').format(racks=', '.join(details['alternatives']))
                               if details['alternatives'] else self.t('wh_no_alternatives'))
            self.message.setText(text)

    def reload(self):
        racks = self.ctrl.get_locations()
        for combo in (self.racks,self.source,self.target):
            selected = combo.currentData()
            combo.clear()
            for rack in racks:
                combo.addItem(rack['location_code'],rack['location_id'])
            combo.setCurrentIndex(max(0,combo.findData(selected)))
        selected = self.product.currentData()
        self.product.clear()
        for product in self.products.get_products():
            self.product.addItem(f"{product['sku']} - {product['name_' + self.lang]}",product['product_id'])
        self.product.setCurrentIndex(max(0,self.product.findData(selected)))
        self.reload_history()

    def complete(self):
        self.reload()
        self.changed.emit()
        self.message.setText(self.t('operation_saved'))

    def receipt(self):
        self.ctrl.add_stock(self.product.currentData(),self.source.currentData(),self.quantity.value())
        self.complete()

    def withdraw(self):
        self.ctrl.withdraw(self.product.currentData(),self.source.currentData(),self.quantity.value(),self.reason.text())
        self.complete()

    def transfer(self):
        text = f"{self.product.currentText()} / {self.source.currentText()} -> {self.target.currentText()} / {self.quantity.value()}"
        if QMessageBox.question(self,self.t('stock_transfer'),text) == QMessageBox.Yes:
            self.ctrl.transfer(self.product.currentData(),self.source.currentData(),self.target.currentData(),self.quantity.value())
            self.complete()

    def create_rack(self):
        self.ctrl.create_rack(self.code.text(),self.weight.text(),self.volume.text())
        self.code.clear()
        self.complete()

    def archive(self):
        dependencies = self.ctrl.rack_dependencies(self.racks.currentData())
        text = f"{dependencies['rack']} / {self.t('quantity')}: {dependencies['stock']} / {self.t('prod_reserved')}: {dependencies['reserved']}\n{self.t('archive_confirmation')}"
        if QMessageBox.question(self,self.t('rack_archive'),text) == QMessageBox.Yes:
            self.ctrl.archive_rack(self.racks.currentData())
            self.complete()

    def invalidate_preview(self):
        self.preview_rows = None
        if hasattr(self,'commit_button'):
            self.commit_button.setEnabled(False)

    def preview(self):
        self.invalidate_preview()
        self.preview_table.setRowCount(0)
        path,_ = QFileDialog.getOpenFileName(self,self.t('delivery_import'),'','CSV (*.csv)')
        if not path:
            return
        rows = self.ctrl.read_delivery(path)
        checked = self.ctrl.preview_delivery(self.delivery_number.text(),rows)
        self.preview_table.setRowCount(len(checked))
        for row, item in enumerate(checked):
            for col, value in enumerate((item['row'],item['sku'],item['name_'+self.lang],item['rack'],item['quantity'],self.t('ready'))):
                self.preview_table.setItem(row,col,QTableWidgetItem(str(value)))
        self.preview_table.resizeColumnsToContents()
        self.preview_rows, self.preview_number = rows, self.delivery_number.text()
        self.commit_button.setEnabled(True)

    def commit(self):
        if self.preview_rows is None:
            return
        if QMessageBox.question(self,self.t('delivery_commit'),self.preview_number) != QMessageBox.Yes:
            return
        self.ctrl.receive_delivery(self.preview_number,self.preview_rows)
        self.invalidate_preview()
        self.complete()

    def example(self):
        path,_ = QFileDialog.getSaveFileName(self,self.t('delivery_example'),'delivery-example.csv','CSV (*.csv)')
        if path:
            with open(path,'w',encoding='utf-8-sig',newline='') as stream:
                writer = csv.writer(stream,delimiter=';')
                writer.writerow(('sku','quantity','rack'))
                writer.writerow(('SKU-001','3','A-01'))

    def reload_history(self):
        rows = self.ctrl.history(*(self.filters[key].currentData() if key == 'operation' else self.filters[key].text().strip()
                                  for key in ('since','until','operation','sku','rack')))
        self.history_table.setRowCount(len(rows))
        self.empty.setVisible(not rows)
        for row, item in enumerate(rows):
            location = item['location_code'] or self.t('data_unavailable')
            if item['is_archived']:
                location += ' / ' + self.t('rack_archived')
            values = (item['created_at'],self.t('operation_'+item['operation'],item['operation']),item['sku'] or '',location,
                      item['quantity'] if item['quantity'] is not None else '',item['actor_login'] or self.t('data_unavailable'),
                      item['operation_id'] or '',item['details'])
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                cell.setToolTip(str(value))
                self.history_table.setItem(row,col,cell)
        self.history_table.resizeColumnsToContents()
