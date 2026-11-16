"""Isolated acceptance regressions for shared sessions and warehouse operations."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication, QLineEdit, QDialog
from controllers import auth_controller
from controllers.auth_controller import AuthController, AuthError
from controllers.warehouse_registry import WarehouseRegistry
from controllers.warehouse_controller import WarehouseController
from controllers.product_controller import ProductController
from controllers.customer_controller import CustomerController
from controllers.pick_list_controller import PickListController
from controllers.sales_controller import SalesController
from models.database import DatabaseManager
from utils.translations import translator

ROOT = Path(__file__).resolve().parents[1]


class ThesisOperationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.auth = AuthController(self.root/'accounts.db')
        self.patch = patch.object(auth_controller,'runtime',self.auth)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.auth.create_account('admin','administrator-secret',first=True)
        self.auth.sign_in('admin','administrator-secret')
        self.registry = WarehouseRegistry(self.auth)
        self.path = self.registry.create(self.root/'warehouse.db')
        self.auth.warehouse = self.path
        self.ctrl = WarehouseController(self.path)
        self.product_data = dict(sku='SKU-Ż',name_pl='Żółty produkt',name_en='Yellow product',price='12.30',weight=1,length=10,width=10,height=10)
        self.pid = ProductController(self.path).save_product(self.product_data)
        self.a = self.ctrl.create_rack('A',100,1)
        self.b = self.ctrl.create_rack('B',100,1)
        self.ctrl.add_stock(self.pid,self.a,10)
        self.person = dict(first_name='Żaneta',last_name='Źródło',street='Długa 1',postal_code='00-001',city='Łódź',email='person@example.test',country='PL')
        self.cid = CustomerController(self.path).save_customer(self.person)
        self.header = dict(channel='shop',external_ref='',payment=1,carrier=1,package_type='INPOST_A',delivery='0',delivery_vat='0',recipient=self.person,customer_id=self.cid,billing={})

    def sql(self, query, params=(), path=None):
        with closing(sqlite3.connect(path or self.path)) as db, db:
            return db.execute(query,params).fetchall()

    def snapshot(self):
        with closing(sqlite3.connect(self.path)) as db:
            return list(db.iterdump())

    def allocated(self):
        sales = SalesController(self.path)
        picking = PickListController(self.path)
        orders=[]
        for qty, date in ((2,'2026-11-01'),(4,'2026-11-10')):
            oid = sales.save(self.header,[dict(product_id=self.pid,quantity=qty,unit='12.30',vat=23)])
            self.sql('UPDATE orders SET order_date=? WHERE order_id=?',(date,oid))
            orders.append(oid)
        options = picking.allocation_options(orders)
        lid = picking.create_list(orders,[dict(order_item_id=i['item_id'],location_id=self.a,quantity=i['quantity']) for i in options])
        return picking,lid,orders

    def test_first_admin_shared_credentials_and_mandatory_password_change(self):
        self.assertFalse(self.auth.needs_setup())
        with self.assertRaises(AuthError):
            self.auth.create_account('another','x',first=True)
        uid = self.auth.create_account('employee','temporary')
        with self.assertRaisesRegex(AuthError,'duplicate'):
            self.auth.create_account('EMPLOYEE','another')
        stored = self.sql('SELECT password_hash FROM accounts WHERE user_id=?',(uid,),self.auth.path)[0][0]
        self.assertNotIn('temporary',stored)
        self.auth.sign_in('employee','temporary')
        with self.assertRaisesRegex(AuthError,'change_required'):
            self.auth.require()
        with self.assertRaises(AuthError):
            self.auth.change_password('wrong','own-secret')
        self.assertTrue(self.auth.session['must_change'])
        self.auth.change_password('temporary','own-secret')
        self.assertEqual(self.auth.require()['user_id'],uid)
        other = AuthController(self.auth.path)
        other.sign_in('employee','own-secret')
        self.auth.sign_in('admin','administrator-secret')
        self.auth.reset_password(uid,'reset-secret')
        with self.assertRaises(AuthError):
            other.require()
        with self.assertRaisesRegex(AuthError,'auth_invalid'):
            other.sign_in('employee','own-secret')
        self.assertIsNone(other.session)
        other.sign_in('employee','reset-secret')
        self.assertTrue(other.session['must_change'])

    def employee(self):
        self.auth.create_account('employee','temporary')
        self.auth.sign_in('employee','temporary')
        self.auth.change_password('temporary','own-secret')

    def test_direct_role_enforcement_and_stale_session(self):
        old = self.ctrl
        self.employee()
        current = WarehouseController(self.path)
        before = self.snapshot()
        for operation in (lambda: current.create_rack('C',1,1),lambda: current.archive_rack(self.b),
                          lambda: ProductController(self.path).delete_product(self.pid),
                          lambda: CustomerController(self.path).delete_customer(self.cid),
                          lambda: self.registry.create(self.root/'forbidden.db'),
                          lambda: self.auth.create_account('bad','secret')):
            with self.assertRaises(AuthError):
                operation()
        self.assertEqual(before,self.snapshot())
        with self.assertRaises(AuthError):
            old.add_stock(self.pid,self.a,1)
        current.add_stock(self.pid,self.a,1)
        self.assertEqual(self.sql("SELECT actor_login FROM operation_history WHERE operation='RECEIPT' ORDER BY event_id DESC LIMIT 1"),[('employee',)])
        self.auth.sign_out()
        with self.assertRaises(AuthError):
            current.withdraw(self.pid,self.a,1,'correction')

    def test_free_withdrawal_preserves_reservations_and_failure_has_no_history(self):
        self.allocated()
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError,'withdraw_free_only'):
            self.ctrl.withdraw(self.pid,self.a,5,'damaged')
        self.assertEqual(before,self.snapshot())
        self.ctrl.withdraw(self.pid,self.a,4,'damaged')
        self.assertEqual(self.sql('SELECT quantity FROM inventory WHERE location_id=?',(self.a,)),[(6,)])
        self.assertEqual(self.sql('SELECT SUM(reserved_quantity) FROM pick_allocations'),[(6,)])
        self.assertEqual(len(self.ctrl.history(operation='WITHDRAWAL')),1)

    def test_transfer_free_first_then_newest_orders_and_stale_picks(self):
        picking,lid,orders = self.allocated()
        old_ids = [i['allocation_id'] for i in picking.get_list(lid)['lines']]
        operation = self.ctrl.transfer(self.pid,self.a,self.b,7)
        self.assertEqual(self.sql('SELECT location_id,quantity FROM inventory ORDER BY location_id'),[(self.a,3),(self.b,7)])
        self.assertEqual(self.sql('SELECT order_id,location_id,SUM(reserved_quantity) FROM pick_allocations WHERE reserved_quantity>0 GROUP BY order_id,location_id ORDER BY order_id,location_id'),
                         [(orders[0],self.a,2),(orders[1],self.a,1),(orders[1],self.b,3)])
        picking.start_list(lid)
        with self.assertRaises(ValueError):
            picking.confirm_pick(old_ids[1],1)
        entries = [e for e in self.ctrl.history() if e['operation_id']==operation]
        self.assertEqual(sorted(e['quantity'] for e in entries),[-7,7])
        for line in picking.get_list(lid)['lines']:
            if line['reserved_quantity']:
                picking.confirm_pick(line['allocation_id'],line['quantity'])
        picking.close_list(lid)
        self.assertEqual(self.sql('SELECT status FROM pick_lists'),[('CLOSED',)])

    def test_small_transfer_and_destination_capacity_rollback(self):
        self.allocated()
        reservations = self.sql('SELECT * FROM pick_allocations')
        self.ctrl.transfer(self.pid,self.a,self.b,3)
        self.assertEqual(reservations,self.sql('SELECT * FROM pick_allocations'))
        self.sql('UPDATE locations SET max_weight=3 WHERE location_id=?',(self.b,))
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError,'capacity_exceeded'):
            self.ctrl.transfer(self.pid,self.a,self.b,1)
        self.assertEqual(before,self.snapshot())

    def test_archive_keeps_identity_history_and_blocks_placement(self):
        with self.assertRaisesRegex(ValueError,'rack_busy'):
            self.ctrl.archive_rack(self.a)
        self.ctrl.transfer(self.pid,self.a,self.b,10)
        self.ctrl.archive_rack(self.a)
        DatabaseManager(self.path)
        self.assertNotIn(self.a,[r['location_id'] for r in self.ctrl.get_locations()])
        self.assertTrue(any(e['is_archived'] for e in self.ctrl.history(location='A')))
        with self.assertRaisesRegex(ValueError,'physical_location_required'):
            self.ctrl.add_stock(self.pid,self.a,1)
        self.assertEqual(self.sql('SELECT is_archived FROM locations WHERE location_id=?',(self.a,)),[(1,)])

    def test_delivery_preview_rollback_additive_duplicate_and_aggregate_capacity(self):
        rows = [dict(sku='SKU-Ż',quantity='3',rack='A')]
        before = self.snapshot()
        preview = self.ctrl.preview_delivery('D-1',rows)
        self.assertEqual(preview[0]['name_pl'],'Żółty produkt')
        self.assertEqual(before,self.snapshot())
        invalid = rows + [dict(sku='UNKNOWN',quantity='1',rack='A')]
        with self.assertRaises(ValueError) as error:
            self.ctrl.receive_delivery('D-1',invalid)
        self.assertEqual(error.exception.details['row'],3)
        self.assertEqual(before,self.snapshot())
        self.ctrl.receive_delivery('D-1',rows)
        self.assertEqual(self.sql('SELECT quantity FROM inventory WHERE location_id=?',(self.a,)),[(13,)])
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError,'delivery_duplicate'):
            self.ctrl.receive_delivery('D-1',[dict(rows[0],quantity='4')])
        with self.assertRaises(ValueError):
            self.ctrl.receive_delivery('D-2',[dict(rows[0],quantity='-1')])
        self.sql('UPDATE locations SET max_weight=18 WHERE location_id=?',(self.a,))
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.ctrl.receive_delivery('D-2',rows+rows)
        self.assertEqual(before,self.snapshot())

    def test_warehouse_creation_registration_isolation_and_delivery_scope(self):
        before = self.snapshot()
        other = self.registry.create(self.root/'second.db')
        self.assertEqual(self.sql('SELECT COUNT(*) FROM products',path=other),[(0,)])
        self.assertEqual(before,self.snapshot())
        with self.assertRaises(ValueError):
            self.registry.create(other)
        invalid = self.root/'invalid.db'
        invalid.write_text('not sqlite')
        with self.assertRaises(ValueError):
            self.registry.register(invalid)
        self.assertNotIn(str(invalid),self.registry.paths())
        rows = [dict(sku='SKU-Ż',quantity='3',rack='A')]
        self.ctrl.receive_delivery('D-1',rows)
        self.auth.warehouse = self.registry.activate(other)
        with self.assertRaises(AuthError):
            self.ctrl.add_stock(self.pid,self.a,1)
        other_ctrl = WarehouseController(other)
        ProductController(other).save_product(self.product_data)
        other_ctrl.create_rack('A',100,1)
        other_ctrl.receive_delivery('D-1',rows)
        self.assertEqual(self.sql('SELECT quantity FROM inventory',path=other),[(3,)])
        self.auth.warehouse = self.registry.activate(self.path)
        self.assertEqual(self.sql('SELECT quantity FROM inventory WHERE location_id=?',(self.a,)),[(13,)])

    def test_history_labels_legacy_actor_unavailable_and_filters(self):
        self.sql("INSERT INTO inventory_transactions(product_id,location_id,quantity_change,transaction_type) VALUES(?,?,1,'LEGACY')",(self.pid,self.a))
        legacy = self.ctrl.history(operation='LEGACY')
        self.assertEqual(len(legacy),1)
        self.assertIsNone(legacy[0]['actor_login'])
        self.assertEqual(self.ctrl.history(product='missing'),[])
        self.assertTrue(self.ctrl.history(product='SKU-Ż',location='A'))

    def test_ui_switch_stay_discard_and_failed_switch_keep_context(self):
        from views.session_host import SessionHost
        other = self.registry.create(self.root/'other.db')
        config = dict(paths=dict(database=self.path,accounts=self.auth.path),localization=dict(language='en'),appearance=dict(theme='light'))
        with patch('views.session_host.QTimer.singleShot'):
            host = SessionHost(config,translator('en',str(ROOT/'utils')))
        self.addCleanup(host.close)
        host.auth.sign_in('admin','administrator-secret')
        host.install(self.path)
        host.set_access(True)
        host.show()
        self.app.processEvents()
        self.assertEqual(host.width(),1280)
        self.assertEqual(host.height(),837)
        if os.environ.get('QA_THESIS_EVIDENCE'):
            host.grab().save(str(Path(os.environ['QA_THESIS_EVIDENCE'])/'session-host.png'))
        field = host.main.view_settings.findChildren(QLineEdit)[0]
        field.setText('Uncommitted draft')
        original = host.main
        host.warehouses.setCurrentIndex(host.warehouses.findData(other))
        with patch.object(host,'discard',return_value=False):
            host.switch()
        self.assertIs(host.main,original)
        self.assertEqual(field.text(),'Uncommitted draft')
        self.assertEqual(host.warehouses.currentData(),self.path)
        host.warehouses.setCurrentIndex(host.warehouses.findData(other))
        with patch.object(host,'discard',return_value=True):
            host.switch()
        self.assertIsNot(host.main,original)
        self.assertEqual(host.main.db_path,other)
        self.assertEqual(host.main.product_ctrl.get_products(),[])
        saved_main = host.main
        host.warehouses.setCurrentIndex(host.warehouses.findData(self.path))
        with patch.object(host,'discard',return_value=True), patch.object(host.registry,'activate',side_effect=ValueError('warehouse_invalid')), patch('views.session_host.QMessageBox.warning'):
            host.switch()
        self.assertIs(host.main,saved_main)
        self.assertEqual(host.warehouses.currentData(),other)
        self.assertEqual(host.auth.active_warehouse(),other)
        updated = dict(host.config,localization=dict(language='pl'))
        host.main.apply_preferences(updated)
        self.app.processEvents()
        self.assertIs(host.controls.parent(),host.main.sidebar_frame)
        self.assertEqual(host.buttons['auth_logout'].text(),'Wyloguj')
        with patch.object(host,'discard',return_value=True):
            host.logout()
        self.assertIsNone(host.main)
        self.assertIsNone(host.auth.session)

    def test_no_implicit_controller_access_without_session(self):
        with patch.object(auth_controller,'runtime',None):
            with self.assertRaisesRegex(AuthError,'auth_required'):
                WarehouseController(self.path).withdraw(self.pid,self.a,1,'test')
            with self.assertRaisesRegex(AuthError,'auth_required'):
                ProductController(self.path).delete_product(self.pid)

    def test_csv_unicode_roundtrip_and_parser_errors(self):
        path = self.root/'receipt.csv'
        path.write_text('sku;quantity;rack\nSKU-Ż;3;A\n',encoding='utf-8-sig')
        rows = self.ctrl.read_delivery(path)
        self.assertEqual(self.ctrl.preview_delivery('D',rows)[0]['name_pl'],'Żółty produkt')
        for text in ('sku;quantity;rack\nSKU-Ż;3\n','not,a,csv','sku;quantity;rack\n'):
            path.write_text(text,encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'delivery_format'):
                self.ctrl.read_delivery(path)

    def test_transfer_equal_order_dates_and_preserved_picked_source(self):
        picking,lid,orders = self.allocated()
        self.sql("UPDATE orders SET order_date='2026-11-01'")
        picking.start_list(lid)
        newer = next(i for i in picking.get_list(lid)['lines'] if i['order_id']==orders[1])
        picking.confirm_pick(newer['allocation_id'],1)
        self.ctrl.transfer(self.pid,self.a,self.b,6)
        original = self.sql('SELECT location_id,picked_quantity,reserved_quantity FROM pick_allocations WHERE allocation_id=?',(newer['allocation_id'],))[0]
        self.assertEqual(original,(self.a,1,0))
        self.assertEqual(self.sql('SELECT order_id,SUM(reserved_quantity) FROM pick_allocations WHERE location_id=? AND reserved_quantity>0 GROUP BY order_id',(self.b,)),[(orders[1],2)])

    def test_qa_language_confirmation_order_errors_and_duplicate_preview(self):
        from main import MainWindow
        from views.orders.order_dialog import OrderDialog
        from PySide6.QtWidgets import QMessageBox, QDialogButtonBox
        previous = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir,previous)
        config = dict(paths=dict(database=self.path),localization=dict(language='pl'),appearance=dict(theme='light',font_size='medium'))
        Path('config.json').write_text(json.dumps(config),encoding='utf-8')
        window = MainWindow(config,translator('pl',str(ROOT/'utils')),self.auth)
        self.addCleanup(window.close)
        # Invoke the real Settings save action and inspect its confirmation language.
        settings = window.view_settings
        settings.cb_lang.setCurrentText('en')
        with patch('PySide6.QtWidgets.QMessageBox.information') as info:
            settings.save_settings()
        self.assertEqual(window.translator.lang_code,'en')
        self.assertEqual(info.call_args.args[2],window.translator.t('saved_now'))
        sales = SalesController(self.path)
        dialog = OrderDialog(window.translator,sales)
        self.addCleanup(dialog.close)
        dialog.fields['channel'].setText('shop')
        dialog.fields['country'].setText('PL')
        dialog.add_line(dict(product_id=self.pid,sku='SKU-Ż'),1,'12.30','bad')
        dialog.save()
        self.assertIn('1',dialog.error.text())
        self.assertIn(window.translator.t('vat'),dialog.error.text())
        dialog.table.item(0,3).setText('23')
        self.assertEqual(dialog.error.text(),'')
        dialog.save()
        self.assertEqual(dialog.result(),QDialog.Accepted)
        self.assertEqual(dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Cancel).text(),window.translator.t('prod_cancel'))
        oid = sales.save(dict(self.header,external_ref='Ref-Ż'),[dict(product_id=self.pid,quantity=1,unit='12.30',vat=23)])
        self.assertIn(('shop','ref-ż'),sales.known_references())
        groups={('shop','ref-ż'):[{'Email':'person@example.test'}]}
        with patch('views.orders.orders_view.QFileDialog.getOpenFileName',return_value=('receipt.csv','')), patch('views.orders.orders_view.read_groups',return_value=groups), patch('views.orders.orders_view.QMessageBox.question',return_value=QMessageBox.No) as question:
            window.view_orders.import_orders()
        self.assertIn(window.translator.t('duplicate'),question.call_args.args[2])
        with patch('views.orders.orders_view.QFileDialog.getOpenFileName',return_value=('bad.json','')), patch('views.orders.orders_view.read_groups',side_effect=ValueError('broken JSON')), patch('views.orders.orders_view.QMessageBox.warning') as warning:
            window.view_orders.import_orders()
        self.assertIn(window.translator.t('import_recovery'),warning.call_args.args[2])

    def test_new_views_localized_and_rendered_at_qa_size(self):
        from main import MainWindow
        from utils.theme_manager import ThemeManager
        from PySide6.QtGui import QFontDatabase
        from PySide6.QtWidgets import QLabel
        fonts = Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'
        for name in ('segoeui.ttf','segoeuib.ttf'):
            if (fonts/name).exists():
                QFontDatabase.addApplicationFont(str(fonts/name))
        person = dict(self.person,first_name='Żaneta Aleksandra',last_name='Źródło-Kowalska',street='Aleja Długiej Nazwy Miejscowości 123/45')
        sales = SalesController(self.path)
        oid = sales.save(dict(self.header,recipient=person),[dict(product_id=self.pid,quantity=1,unit='12.30',vat=23) for _ in range(30)])
        self.ctrl.add_stock(self.pid,self.a,20)
        picking = PickListController(self.path)
        options = picking.allocation_options([oid])
        lid = picking.create_list([oid],[dict(order_item_id=i['item_id'],location_id=self.a,quantity=1) for i in options])
        picking.start_list(lid)
        for line in picking.get_list(lid)['lines']:
            picking.confirm_pick(line['allocation_id'],1)
        picking.close_list(lid)
        from controllers.dispatch_controller import DispatchController
        from views.orders.dispatch_view import DispatchDialog
        DispatchController(self.path).add_parcel(oid,'CUSTOM_BOX',1,{i['item_id']:1 for i in options})
        evidence = os.environ.get('QA_THESIS_EVIDENCE')
        for lang in ('pl','en'):
            for theme in ('light','dark','modern'):
                ThemeManager.apply_theme(self.app,theme,'medium')
                config=dict(paths=dict(database=self.path),localization=dict(language=lang),appearance=dict(theme=theme))
                window=MainWindow(config,translator(lang,str(ROOT/'utils')),self.auth)
                window.resize(1280,837)
                window.show()
                try:
                    window.stacked_widget.setCurrentWidget(window.view_orders)
                    row=window.view_orders.order_rows[0]
                    row.summary_row.set_expanded(True)
                    self.app.processEvents()
                    self.assertEqual(window.width(),1280)
                    self.assertEqual(row.products_table.rowCount(),30)
                    self.assertTrue(any(person['street'] in label.text() and label.wordWrap() for label in row.details_panel.findChildren(QLabel)))
                    for page,tab in (('orders',None),('stock',0),('racks',1),('delivery',2),('history',3)):
                        if tab is not None:
                            window.open_warehouse()
                            window.view_warehouse.tabs.setCurrentIndex(tab)
                        self.app.processEvents()
                        if evidence:
                            Path(evidence).mkdir(parents=True,exist_ok=True)
                            self.assertTrue(window.grab().save(str(Path(evidence)/f'{page}-{lang}-{theme}.png')))
                finally:
                    window.close()
                    window.deleteLater()
                    self.app.processEvents()
                parcel = DispatchDialog(translator(lang,str(ROOT/'utils')),self.path,oid,confirm=True)
                parcel.show()
                parcel.parcel_table.selectRow(0)
                self.app.processEvents()
                try:
                    self.assertEqual(parcel.parcel_details.toPlainText().count('SKU-Ż'),30)
                    if evidence:
                        self.assertTrue(parcel.grab().save(str(Path(evidence)/f'parcel-{lang}-{theme}.png')))
                finally:
                    parcel.close()
                    parcel.deleteLater()
                    self.app.processEvents()


if __name__=='__main__':
    unittest.main()
