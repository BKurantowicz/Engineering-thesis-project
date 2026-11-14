"""Integration tests for transactional order entry and multi-parcel dispatch."""
import csv
from contextlib import closing
from email import policy
from email.parser import BytesParser
import gc
import json
import os
from pathlib import Path
import socketserver
import sqlite3
import tempfile
import threading
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from unittest.mock import patch
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
from controllers.customer_controller import CustomerController
from controllers.dispatch_controller import DispatchController
from controllers.dispatch_mail import DispatchMail, invoice_pdf
from controllers.inventory_controller import InventoryController
from controllers.order_controller import OrderController
from controllers.order_import import read_groups, import_group
from controllers.pick_list_controller import PickListController
from controllers.product_controller import ProductController
from controllers.sales_controller import SalesController, priced_line
from models.database import DatabaseManager
from utils.translations import translator
from views.orders.order_dialog import OrderDialog
from views.orders.dispatch_view import DispatchDialog


class LocalSMTP(socketserver.StreamRequestHandler):
    """Receive mail solely on loopback and capture the actual MIME payload."""
    def handle(self):
        self.wfile.write(b"220 localhost test\r\n")
        while raw := self.rfile.readline():
            verb=raw.split(maxsplit=1)[0].upper()
            if verb==b"DATA":
                self.wfile.write(b"354 Send data\r\n")
                parts=[]
                for line in self.rfile:
                    if line==b".\r\n":
                        break
                    parts.append(line)
                self.server.messages.append(BytesParser(policy=policy.default).parsebytes(b"".join(parts)))
            elif verb == b"QUIT":
                self.wfile.write(b"221 Closing\r\n")
                return
            self.wfile.write(b"250 OK\r\n")


class SalesDispatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        cls.lang=translator("pl",str(Path(__file__).resolve().parents[1]/"utils"))

    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(gc.collect)
        self.root=Path(tmp.name)
        self.path=str(self.root/"business.db")
        DatabaseManager(self.path)
        self.sales=SalesController(self.path)
        self.pick=PickListController(self.path)
        self.ship=DispatchController(self.path)
        self.mail=DispatchMail(self.path)
        self.product=ProductController(self.path)
        self.data=dict(sku="SKU-A",name_pl="Łącznik",name_en="Joint",price="12.30",weight=1,length=1,width=1,height=1,ean="0123456789012")
        self.pid=self.product.save_product(self.data)
        person=dict(first_name="Łukasz",last_name="Żuk",street="Długa 1",postal_code="00-001",city="Łódź",email="test@example.test",country="PL")
        cid=CustomerController(self.path).save_customer(person)
        self.header=dict(channel="shop",external_ref="A1",payment=1,carrier=1,package_type="INPOST_A",delivery="10.80",delivery_vat="8",
                         recipient=person,customer_id=cid,billing={})
        self.lines=[dict(product_id=self.pid,quantity=3,unit="12.30",vat=23)]

    def sql(self,query,params=()):
        with closing(sqlite3.connect(self.path)) as db,db:
            return db.execute(query,params).fetchall()

    def picked(self):
        oid=self.sales.save(self.header,self.lines)
        self.sql("INSERT INTO locations(location_code,max_weight,max_volume) VALUES('A',100,1)")
        loc=self.sql("SELECT location_id FROM locations WHERE location_code='A'")[0][0]
        InventoryController(self.path).add_stock(self.pid,loc,3)
        item=self.pick.allocation_options([oid])[0]["item_id"]
        lid=self.pick.create_list([oid],[dict(order_item_id=item,location_id=loc,quantity=3)])
        self.pick.start_list(lid)
        self.pick.confirm_pick(self.pick.get_list(lid)["lines"][0]["allocation_id"],3)
        with self.assertRaisesRegex(ValueError,"packing_locked"):
            self.ship.add_parcel(oid,"INPOST_A",1,{item:1})
        self.pick.close_list(lid)
        return oid,item

    def test_sales_prices_states_filters_and_rollback(self):
        self.assertEqual(priced_line(3,"0.05",23)["net_cents"],12)
        oid=self.sales.save(self.header,[dict(self.lines[0],quantity=2)])
        order,_=self.sales.details(oid)
        self.assertEqual((order["total_amount"],order["net_cents"]),(35.40,3000))
        self.assertEqual(self.sql("SELECT count(*) FROM pick_allocations"),[(0,)])
        self.sales.change_state(oid,"hold")
        self.assertFalse(self.pick.get_eligible_orders())
        self.sales.change_state(oid,"resume")
        with self.assertRaises(ValueError):
            self.sales.save(self.header,[dict(self.lines[0],quantity=-1)],oid)
        self.assertEqual(self.sales.details(oid)[0]["total_amount"],35.4)
        query=OrderController(self.path)
        self.assertEqual([r["order_id"] for r in query.get_orders(product="łącz",destination="ŁÓDŹ",channel="Shop")],[oid])
        self.sales.change_state(oid,"cancel")
        self.assertEqual(self.sales.details(oid)[0]["status_code"],"CANCELLED")
        for _ in range(2):
            self.sales.save(dict(self.header,external_ref=""),self.lines)
        self.assertEqual(self.sql("SELECT count(*) FROM orders"),[(3,)])

    def test_order_import_group_identity_blank_customer_and_invalid_sku(self):
        line=dict(Platforma="Shop",Nr_Zewnetrzny="1",Imie="Anna",Nazwisko="Kot",Ulica="Długa",Kod_Pocztowy="00-001",Miasto="Łódź",
                  Kraj="PL",Kurier="InPost",Typ_Wysylki="INPOST_A",Platnosc="BLIK",SKU="SKU-A",Ilosc="1",Cena_Sztuka="12.30",VAT="23")
        path=self.root/"orders.csv"
        with path.open("w",encoding="utf-8-sig",newline="") as f:
            writer=csv.DictWriter(f,fieldnames=line,delimiter=";")
            writer.writeheader()
            writer.writerows([line,line])
        rows=next(iter(read_groups(path).values()))
        choices=self.sales.choices()
        with self.assertRaisesRegex(ValueError,"customer_id"):
            import_group(self.sales,rows,choices)
        order=import_group(self.sales,rows,choices,"new")
        self.assertEqual(len(self.sales.details(order)[1]),2)
        with self.assertRaisesRegex(ValueError,"duplicate"):
            import_group(self.sales,rows,choices,"new")
        with self.assertRaises(ValueError):
            import_group(self.sales,[dict(line,Nr_Zewnetrzny="2",SKU="missing")],choices,"new")
        self.assertEqual(self.sql("SELECT count(*) FROM customers"),[(2,)])

    def test_pack_export_confirm_invoice_and_actual_smtp(self):
        oid,item=self.picked()
        with self.assertRaisesRegex(ValueError,"order_locked"):
            self.sales.change_state(oid,"hold")
        a=self.ship.add_parcel(oid,"INPOST_A",1,{item:2})
        with self.assertRaisesRegex(ValueError,"excess"):
            self.ship.add_parcel(oid,"INPOST_A",1,{item:2})
        b=self.ship.add_parcel(oid,"INPOST_A",1,{item:1})
        self.assertEqual(self.sql("SELECT SUM(quantity) FROM inventory"),[(0,)])
        paths=self.ship.export([a,b],self.root)
        with paths[0].open(encoding="utf-8-sig") as f:
            rows=list(csv.DictReader(f,delimiter=";"))
        self.assertEqual([(r["dispatch_id"],r["contents"]) for r in rows],[(str(a),"SKU-A × 2"),(str(b),"SKU-A × 1")])
        server=socketserver.TCPServer(("127.0.0.1",0),LocalSMTP)
        server.messages=[]
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        config=dict(paths=dict(exports_invoices=str(self.root)),email_smtp=dict(host="127.0.0.1",port=server.server_address[1],security="LOCAL",sender="sender@example.test"))
        records=[(f"ORD-{oid:05d}",str(d),f"TEST-{d}") for d in (b,a)]
        returns=self.root/"confirm.csv"
        returns.write_text("order_ref;dispatch_id;tracking\n"+"\n".join(";".join(r) for r in [*records,records[1]]),encoding="utf-8-sig")
        self.assertEqual([s for _,s in self.ship.preview(returns)],["ready","ready","duplicate"])
        for idx,record in enumerate(records):
            self.assertEqual(self.ship.confirm(record,{"name":"Test seller"},"pl"),"accepted")
            self.assertEqual(self.ship.confirm(record,{},"pl"),"duplicate")
            self.assertEqual(self.mail.send(int(record[1]),config,self.lang),"sent")
            self.assertEqual(self.mail.send(int(record[1]),config,self.lang),"sent")
            self.assertEqual(self.sql("SELECT count(*) FROM invoices"),[(idx,)])
            self.assertEqual(self.sql("SELECT status_code FROM orders"),[("SHIPPED" if idx else "PACKED",)])
        self.assertEqual(len(server.messages),2)
        for delivered in server.messages:
            self.assertIsNotNone(delivered.get_body(preferencelist=("plain",)))
            rendered = delivered.get_body(preferencelist=("html",)).get_content()
            self.assertIn("Łącznik", rendered)
            self.assertIn("12.30", rendered)
            self.assertIn("Łódź", rendered)
        self.assertEqual(len(list(server.messages[0].iter_attachments())),0)
        self.assertTrue(next(server.messages[1].iter_attachments()).get_payload(decode=True).startswith(b"%PDF-"))
        self.assertEqual(len(OrderController(self.path).get_orders()),1)
        invoice=self.mail.invoice_for(oid)
        self.assertTrue(invoice_pdf(self.path,invoice,self.root,self.lang).exists())

    def test_missing_smtp_keeps_dispatch_and_explains_failure_without_connecting(self):
        oid,item=self.picked()
        shipment=self.ship.add_parcel(oid,"INPOST_A",1,{item:3})
        self.ship.confirm((f"ORD-{oid}",str(shipment),"NO-SMTP"),{},"pl")
        config={"paths":{},"email_smtp":{}}
        html,warning=self.mail.preview(shipment,config,self.lang)
        self.assertIn("NO-SMTP",html)
        with patch("smtplib.SMTP") as smtp, patch("smtplib.SMTP_SSL") as secure:
            self.assertEqual(self.mail.send(shipment,config,self.lang),"failed")
        smtp.assert_not_called()
        secure.assert_not_called()
        self.assertEqual(self.mail.get(shipment)["detail"],"smtp_setup")
        self.assertEqual(self.sql("SELECT status_code FROM orders"),[("SHIPPED",)])
        self.assertEqual(self.sql("SELECT count(*) FROM invoices"),[(1,)])
        dialog=DispatchDialog(self.lang,self.path,oid)
        dialog.mail_result(shipment,"failed")
        self.assertIn("SMTP",dialog.message.text())
        self.assertIn("Nadanie",dialog.message.text())
        dialog.close()

    def test_order_edit_keeps_original_product_snapshot(self):
        oid=self.sales.save(self.header,self.lines)
        self.product.save_product(dict(self.data,sku="RENAMED",name_pl="Inna nazwa",weight=2),self.pid)
        dialog=OrderDialog(self.lang,self.sales,oid)
        self.assertEqual(dialog.table.item(0,0).text(),"SKU-A")
        dialog.save()
        self.assertEqual(dialog.result(),QDialog.Accepted)
        saved=json.loads(self.sales.details(oid)[1][0]["sale_snapshot"])
        self.assertEqual((saved["sku"],saved["name_pl"],saved["weight"]),("SKU-A","Łącznik",1))
        dialog.close()

    def test_stale_preview_requires_current_uncertain_delivery_acknowledgement(self):
        oid,item=self.picked()
        shipment=self.ship.add_parcel(oid,"INPOST_A",1,{item:3})
        self.ship.confirm((f"ORD-{oid}",str(shipment),"TEST-1"),{},"pl")
        dlg=DispatchDialog(self.lang,self.path,oid)
        dlg.parcel_table.selectRow(0)
        self.sql("UPDATE dispatch_mail SET state='uncertain' WHERE shipment_id=?",(shipment,))
        with patch.object(QMessageBox,"question",return_value=QMessageBox.No) as confirm, patch.object(dlg,"send") as send:
            dlg.retry()
            confirm.assert_called_once()
            send.assert_not_called()
        dlg.close()

    def test_recipient_search_and_unicode_reference_identity(self):
        recipient=dict(self.header["recipient"],first_name="New",last_name="Recipient")
        oid=self.sales.save(dict(self.header,channel="Straße",recipient=recipient),self.lines)
        found=OrderController(self.path).get_orders(destination="new recipient")
        self.assertEqual([r["order_id"] for r in found],[oid])
        with self.assertRaisesRegex(ValueError,"duplicate"):
            self.sales.save(dict(self.header,channel="STRASSE"),self.lines)

    def test_duplicate_dispatch_spellings_reject_conflicts_before_writes(self):
        oid,item=self.picked()
        dispatch=self.ship.add_parcel(oid,"INPOST_A",1,{item:3})
        path=self.root/"carrier.csv"
        path.write_text(f"order_ref;dispatch_id;tracking\nORD-{oid};{dispatch};A\nORD-{oid:05d};0{dispatch};B\n",encoding="utf8")
        self.assertEqual([state for _,state in self.ship.preview(path)],["tracking_conflict","tracking_conflict"])
        self.assertEqual(self.sql("SELECT tracking_number FROM order_shipments"),[(None,)])

    def test_dialog_scan_rejects_suffix_and_reuses_identifier(self):
        oid,_=self.picked()
        dialog=DispatchDialog(self.lang,self.path,oid)
        dialog.scan.setText("A")
        dialog.scan_one()
        self.assertFalse(dialog.draft)
        dialog.show()
        dialog.scan.setFocus()
        QTest.keyClicks(dialog.scan,self.data["ean"])
        QTest.keyClick(dialog.scan,Qt.Key_Return)
        self.assertEqual(dialog.message.text(),"")
        self.assertEqual(sum(dialog.draft.values()),1)
        dialog.seal()
        self.assertEqual(len(self.ship.parcels(oid)),1)
        dialog.close()
        form=OrderDialog(self.lang,self.sales)
        form.add_selected()
        self.assertEqual(len(form.lines()),1)
        form.reject()
