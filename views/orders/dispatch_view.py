"""Packing station, carrier exchange and dispatch notification history."""
import csv
import json
import sqlite3
import uuid

from PySide6.QtCore import QThread, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from controllers.dispatch_controller import DispatchController
from controllers.dispatch_mail import DispatchMail, invoice_pdf, mail_text
from controllers.sales_controller import SalesController
from controllers.settings_controller import SettingsController


class MailWorker(QThread):
    result = Signal(int,str)
    def __init__(self,db_path,ids,config,translator,uncertain,parent):
        super().__init__(parent)
        self.mail=DispatchMail(db_path)
        self.ids,self.config,self.translator,self.uncertain=ids,config,translator,set(uncertain)

    def run(self):
        for shipment in self.ids:
            try:
                state=self.mail.send(shipment,self.config,self.translator,shipment in self.uncertain)
            except (OSError,ValueError,sqlite3.Error):
                state="uncertain"
            self.result.emit(shipment,state)


class DispatchDialog(QDialog):
    def __init__(self,translator,db_path,order_id=None,parent=None,confirm=False):
        super().__init__(parent)
        self.translator,self.t=translator,translator.t
        self.db_path,self.fixed_order=db_path,order_id
        self.ctrl=DispatchController(db_path)
        self.mail=DispatchMail(db_path)
        self.config=SettingsController().get_config()
        self.draft={}
        self.token=uuid.uuid4().hex
        self.worker=None
        self.setWindowTitle(self.t("dispatch"))
        self.resize(950,620)
        layout=QVBoxLayout(self)
        self.tabs=QTabWidget()
        layout.addWidget(self.tabs)
        pack=QWidget()
        packing=QVBoxLayout(pack)
        self.tabs.addTab(pack,self.t("packing"))
        self.orders=QComboBox()
        ids=[order_id] if order_id is not None else self.ctrl.work_orders()
        for oid in ids:
            self.orders.addItem(f"ORD-{oid:05d}",oid)
        packing.addWidget(self.orders)
        selectors=QHBoxLayout()
        self.box=QComboBox()
        self.carrier=QComboBox()
        choices=SalesController(db_path).choices()
        for row in choices["types"]:
            self.box.addItem(f"{row['package_code']} · {row['base_cost']:.2f} PLN",row["package_code"])
        for row in choices["carriers"]:
            self.carrier.addItem(row["carrier_name"]+" · "+row["service_name_"+translator.lang_code],row["shipping_id"])
        selectors.addWidget(self.box)
        selectors.addWidget(self.carrier)
        packing.addLayout(selectors)
        self.scan=QLineEdit()
        self.scan.setPlaceholderText(self.t("scan_code"))
        self.scan.returnPressed.connect(self.scan_one)
        packing.addWidget(self.scan)
        self.lines=self.table(("tbl_sku","product","remaining","draft"))
        packing.addWidget(self.lines)
        row=QHBoxLayout()
        self.button(row,"scan_add",self.scan_one)
        self.button(row,"clear_draft",self.clear_draft)
        self.button(row,"seal_parcel",self.seal)
        packing.addLayout(row)
        exchange=QWidget()
        shipping=QVBoxLayout(exchange)
        self.tabs.addTab(exchange,self.t("dispatch"))
        self.parcel_table=self.table(("sale_order","dispatch_id","package_type","carrier","basket","tracking","state","mail_state"))
        self.parcel_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        shipping.addWidget(self.parcel_table)
        bar=QHBoxLayout()
        for key,slot in (("export",self.export),("confirm_file",self.import_file),("invoice",self.open_invoice),
                         ("preview_mail",self.preview_mail),("retry_mail",self.retry)):
            self.button(bar,key,slot)
        shipping.addLayout(bar)
        self.message=QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.orders.currentIndexChanged.connect(self.choose_order)
        self.choose_order()
        if confirm:
            self.tabs.setCurrentIndex(1)

    def table(self,keys):
        table=QTableWidget(0,len(keys))
        table.setHorizontalHeaderLabels([self.t(k,k) for k in keys])
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        return table

    def button(self,layout,key,slot):
        button=QPushButton(self.t(key,key))
        button.setAutoDefault(False)
        button.clicked.connect(lambda: self.guarded(slot))
        layout.addWidget(button)

    def guarded(self,slot):
        try:
            slot()
        except (ValueError,sqlite3.Error,OSError,csv.Error) as error:
            self.message.setText(self.t(str(error),str(error)))

    def choose_order(self):
        self.draft.clear()
        oid=self.orders.currentData()
        if oid is not None:
            order,_=SalesController(self.db_path).details(oid)
            snapshot=json.loads(order["sales_snapshot"] or "{}")
            for combo,key in ((self.carrier,"carrier"),(self.box,"package_type")):
                idx=combo.findData(snapshot.get(key))
                if idx>=0:
                    combo.setCurrentIndex(idx)
        self.refresh()

    def clear_draft(self):
        self.draft.clear()
        self.token=uuid.uuid4().hex
        self.refresh()

    def refresh(self):
        self.items=self.ctrl.packing_lines(self.orders.currentData())
        self.lines.setRowCount(len(self.items))
        for r,item in enumerate(self.items):
            for c,val in enumerate((item["sku"],item["name_"+self.translator.lang_code],item["remaining"],self.draft.get(item["item_id"],0))):
                self.lines.setItem(r,c,QTableWidgetItem(str(val)))
        self.lines.resizeColumnsToContents()
        self.lines.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch)
        self.parcels=self.ctrl.parcels(self.fixed_order)
        self.parcel_table.setRowCount(len(self.parcels))
        for r,p in enumerate(self.parcels):
            state="sent_parcel" if p["dispatched_at"] else ("ready" if p["status_code"]=="PACKED" else "packing")
            for c,val in enumerate((f"ORD-{p['order_id']:05d}",p["shipment_id"],p["package_code"],p["carrier_name"],
                                    p["contents"],p["tracking_number"] or "—",self.t(state),self.t(p["mail_state"] or "", "—"))):
                self.parcel_table.setItem(r,c,QTableWidgetItem(str(val)))
        self.parcel_table.resizeColumnsToContents()

    def scan_one(self):
        code=self.scan.text().strip().casefold()
        if not code:
            return
        self.scan.clear()
        matches=[i for i in self.items if code and code in (i["sku"].casefold(),i["ean"])]
        available=[i for i in matches if i["remaining"]>self.draft.get(i["item_id"],0)]
        if len({i["product_id"] for i in matches})!=1 or not available or self.orders.currentData() not in self.ctrl.work_orders():
            self.message.setText(self.t("excess"))
            return
        item=available[0]["item_id"]
        self.draft[item]=self.draft.get(item,0)+1
        self.message.clear()
        self.refresh()

    def seal(self):
        shipment=self.ctrl.add_parcel(self.orders.currentData(),self.box.currentData(),self.carrier.currentData(),self.draft,self.token)
        self.clear_draft()
        self.message.setText(f"{self.t('dispatch_id')}: {shipment}")
        self.tabs.setCurrentIndex(1)

    def selection(self):
        return [self.parcels[i.row()] for i in self.parcel_table.selectionModel().selectedRows()]

    def export(self):
        ids=[p["shipment_id"] for p in self.selection()]
        paths=self.ctrl.export(ids,self.config["paths"].get("exports_carriers") or "Exports")
        self.message.setText("\n".join(str(p) for p in paths))

    def import_file(self):
        if self.worker and self.worker.isRunning():
            return
        path,_=QFileDialog.getOpenFileName(self,self.t("confirm_file"),self.config["paths"].get("imports_default",""),"CSV (*.csv)")
        if not path:
            return
        rows=self.ctrl.preview(path)
        if not rows:
            raise ValueError("file_format")
        preview="\n".join(" · ".join((*record,self.t(state,state))) for record,state in rows)
        if QMessageBox.question(self,self.t("confirm_file"),preview)!=QMessageBox.Yes:
            return
        ids,report=[],[]
        for record,state in rows:
            if state=="ready":
                try:
                    state=self.ctrl.confirm(record,self.config.get("company_info",{}),self.translator.lang_code)
                    if state=="accepted":
                        ids.append(int(record[1]))
                except (ValueError,sqlite3.Error) as error:
                    state=str(error)
            report.append(" · ".join((*record,self.t(state,state))))
        self.refresh()
        QMessageBox.information(self,self.t("confirm_file"),"\n".join(report))
        self.send(ids)

    def open_invoice(self):
        selected=self.selection()
        oid=selected[0]["order_id"] if selected else self.fixed_order
        invoice=self.mail.invoice_for(oid)
        if invoice is None:
            raise ValueError("no_invoice")
        path=invoice_pdf(self.db_path,invoice,self.config["paths"].get("exports_invoices") or "Invoices",self.translator)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve()))):
            raise OSError(str(path))

    def preview_mail(self):
        selected=self.selection()
        job=self.mail.get(selected[0]["shipment_id"]) if selected else None
        if not job:
            raise ValueError("not_ready")
        text=mail_text(json.loads(job["message"]),self.translator)
        if job["invoice_id"]:
            text+="\nPDF · "+self.t("invoice")
        QMessageBox.information(self,self.t("preview_mail"),text)

    def retry(self):
        selected=self.selection()
        ids=[p["shipment_id"] for p in selected]
        uncertain=[sid for sid in ids if (self.mail.get(sid) or {}).get("state")=="uncertain"]
        if uncertain:
            if QMessageBox.question(self,self.t("uncertain"),self.t("retry_uncertain"))!=QMessageBox.Yes:
                return
        self.send(ids,uncertain)

    def send(self,ids,uncertain=()):
        if not ids or self.worker and self.worker.isRunning():
            return
        self.worker=MailWorker(self.db_path,ids,self.config,self.translator,uncertain,self)
        self.worker.result.connect(self.mail_result)
        self.worker.start()

    def mail_result(self,dispatch,state):
        self.message.setText(f"{self.t('dispatch_id')} {dispatch} · {self.t(state,state)}")
        self.refresh()

    def reject(self):
        if not self.worker or not self.worker.isRunning():
            super().reject()
