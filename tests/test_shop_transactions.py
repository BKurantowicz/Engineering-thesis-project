"""Competing installations, mail origin, settings rollback, and private history."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch, MagicMock

import test_shop_operations as operations
from controllers.auth_controller import AuthError
from controllers.dispatch_controller import DispatchController
from controllers.dispatch_mail import DispatchMail
from controllers.settings_controller import SettingsController
from controllers.warehouse_controller import WarehouseController
from utils.translations import translator


ROOT = Path(__file__).resolve().parents[1]


class ShopTransactionTests(unittest.TestCase):
    def setUp(self):
        self.f = operations.ShopOperationsTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def dispatch(self, reference):
        f = self.f
        order = f.order(1,reference)
        picking,lid,item = f.allocate(order,[(f.r2,1)])
        picking.start_list(lid)
        picking.confirm_pick(picking.get_list(lid)['lines'][0]['allocation_id'],1)
        picking.close_list(lid)
        dispatch = DispatchController(f.path)
        shipment = dispatch.add_parcel(order,'CUSTOM_BOX',1,{item:1})
        dispatch.confirm((f'ORD-{order:05d}',str(shipment),'TRACK-'+reference),{'name':'Wrong active settings'},'en')
        return shipment

    def test_competing_processes_reserve_shared_stock_only_once(self):
        f = self.f
        a = f.order(6)
        f.auth.select_context(f.b,f.w2)
        b = f.order(6)
        code = '''
import sys
from controllers import auth_controller as auth
from controllers.auth_controller import AuthController
from controllers.pick_list_controller import PickListController
path,shop,warehouse,order,rack=sys.argv[1:]
auth.runtime=AuthController(path)
auth.runtime.sign_in('admin','password')
auth.runtime.select_context(int(shop),int(warehouse))
controller=PickListController(path)
try:
    item=controller.allocation_options([int(order)])[0]['item_id']
    controller.create_list([int(order)],[dict(order_item_id=item,location_id=int(rack),quantity=6)])
    print('reserved')
except ValueError as error:
    print(str(error))
'''
        processes = [subprocess.Popen([sys.executable,'-B','-c',code,f.path,str(shop),str(f.w2),str(order),str(f.r2)],
                     cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for shop,order in ((1,a),(f.b,b))]
        results = []
        for process in processes:
            out,error = process.communicate(timeout=30)
            self.assertEqual(process.returncode,0,error)
            results.append(out.strip())
        self.assertEqual(sorted(results),['insufficient_available','reserved'])
        with closing(sqlite3.connect(f.path)) as db:
            self.assertEqual(db.execute('SELECT SUM(reserved_quantity) FROM pick_allocations').fetchone()[0],6)

    def test_independent_invoice_sequences_and_originating_shop_smtp(self):
        f = self.f
        smtp = dict(host='127.0.0.1',port=8025,security='LOCAL')
        f.shop.save_settings(1,dict(company_info={'name':'Shop A'},email_smtp=dict(smtp,sender='a@example.test')))
        f.shop.save_settings(f.b,dict(company_info={'name':'Shop B'},email_smtp=dict(smtp,sender='b@example.test')))
        shipment = self.dispatch('A1')
        old = DispatchMail(f.path)
        f.auth.select_context(f.b,f.w2)
        self.dispatch('B1')
        with self.assertRaises(AuthError):
            old.send(shipment,{},translator('en',str(ROOT/'utils')))
        f.auth.select_context(1,f.w2)
        self.dispatch('A2')
        with closing(sqlite3.connect(f.path)) as db:
            numbers = db.execute('SELECT shop_id,invoice_number FROM invoices ORDER BY invoice_id').fetchall()
        self.assertEqual([number.rsplit('/',1)[1] for _,number in numbers],['000001','000001','000002'])
        pdf = Path(f.tmp.name)/'invoice.pdf'
        pdf.write_bytes(b'%PDF-1.4\nmock attachment')
        sent = []
        smtp_mock = MagicMock()
        smtp_mock.send_message.side_effect = sent.append
        with patch('controllers.dispatch_mail.smtplib.SMTP',return_value=smtp_mock), patch('controllers.dispatch_mail.invoice_pdf',return_value=pdf):
            result = DispatchMail(f.path).send(shipment,{'paths':{},'email_smtp':dict(smtp,sender='b@example.test')},translator('en',str(ROOT/'utils')))
        self.assertEqual(result,'sent')
        self.assertEqual(len(sent),1)
        self.assertEqual(sent[0]['From'],'a@example.test')

    def test_switch_before_submission_restores_only_originating_claim(self):
        f = self.f
        f.shop.save_settings(1,dict(email_smtp=dict(host='127.0.0.1',port=8025,security='LOCAL',sender='a@example.test')))
        shipment = self.dispatch('A')
        pdf = Path(f.tmp.name)/'invoice.pdf'
        pdf.write_bytes(b'%PDF-1.4\nmock attachment')
        smtp = MagicMock()
        def switch(*args,**kwargs):
            f.auth.select_context(f.b,f.w2)
            return smtp
        with patch('controllers.dispatch_mail.smtplib.SMTP',side_effect=switch), patch('controllers.dispatch_mail.invoice_pdf',return_value=pdf):
            with self.assertRaises(AuthError):
                DispatchMail(f.path).send(shipment,{'paths':{}},translator('en',str(ROOT/'utils')))
        smtp.send_message.assert_not_called()
        with closing(sqlite3.connect(f.path)) as db:
            self.assertEqual(db.execute('SELECT state,claimed_at FROM dispatch_mail WHERE shipment_id=?',(shipment,)).fetchone(),('pending',None))

    def test_missing_shop_smtp_cannot_fall_back_to_another_shops_supplied_config(self):
        f = self.f
        f.auth.select_context(f.b,f.w2)
        shipment = self.dispatch('B-NO-SMTP')
        config = dict(email_smtp=dict(host='127.0.0.1',port=8025,security='LOCAL',sender='wrong@example.test'))
        with patch('controllers.dispatch_mail.smtplib.SMTP') as smtp:
            state = DispatchMail(f.path).send(shipment,config,translator('en',str(ROOT/'utils')))
        self.assertEqual(state,'failed')
        smtp.assert_not_called()

    def test_failed_global_settings_write_preserves_shop_and_file_and_stale_controller_is_blocked(self):
        f = self.f
        path = Path(f.tmp.name)/'config.json'
        path.write_text('{"appearance":{"theme":"dark"}}',encoding='utf-8')
        ctrl = SettingsController(str(path))
        config = ctrl.get_config()
        config['company_info'] = {'name':'Changed'}
        before,file_before = f.dump(),path.read_bytes()
        with patch('controllers.settings_controller.os.replace',side_effect=OSError('injected')):
            with self.assertRaises(OSError):
                ctrl.save_config(config)
        self.assertEqual(f.dump(),before)
        self.assertEqual(path.read_bytes(),file_before)
        f.auth.select_context(f.b,f.w2)
        with self.assertRaises(AuthError):
            ctrl.save_config(config)

    def test_shared_history_masks_foreign_shop_details_and_hides_unassigned_warehouses(self):
        f = self.f
        with closing(sqlite3.connect(f.path)) as db, db:
            for location in (f.r1,f.r2):
                db.execute('''INSERT INTO operation_history(operation,operation_id,product_id,location_id,quantity,details,shop_id)
                    VALUES('RETURN','PRIVATE-ORDER',?,?,1,'private.customer@example.test',1)''',(f.product,location))
        uid = f.auth.create_account('worker','temporary')
        f.shop.assign_employee(uid,[f.b])
        f.auth.sign_in('worker','temporary')
        f.auth.change_password('temporary','worker-password')
        f.auth.select_context(f.b,f.w2)
        rows = WarehouseController(f.path).history(operation='RETURN')
        self.assertEqual(len(rows),1)
        self.assertNotIn('PRIVATE-ORDER',json.dumps(rows))
        self.assertNotIn('private.customer',json.dumps(rows))
        self.assertEqual(rows[0]['warehouse_id'],f.w2)


if __name__=='__main__':
    unittest.main()
