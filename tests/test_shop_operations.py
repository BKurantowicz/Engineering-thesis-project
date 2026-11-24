"""Shop isolation and shared physical stock through real business controllers."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from controllers import auth_controller
from controllers.auth_controller import AuthController, AuthError
from controllers.shop_controller import ShopController
from controllers.customer_controller import CustomerController
from controllers.product_controller import ProductController
from controllers.sales_controller import SalesController
from controllers.pick_list_controller import PickListController
from controllers.dispatch_controller import DispatchController
from controllers.warehouse_controller import WarehouseController
from models.database import DatabaseManager
from models.shop_schema import initialize_shop_schema


class ShopOperationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name)/'application.db')
        DatabaseManager(self.path)
        with closing(sqlite3.connect(self.path)) as db:
            initialize_shop_schema(db)
        self.auth = AuthController(self.path)
        self.auth.create_account('admin','password',first=True)
        self.auth.sign_in('admin','password')
        self.enterContext(patch.object(auth_controller,'runtime',self.auth))
        self.shop = ShopController(self.auth)
        self.b = self.shop.save_shop('Shop B')
        self.w2 = self.shop.create_warehouse('W2')
        self.shop.assign_warehouses(1,[1,self.w2])
        self.shop.assign_warehouses(self.b,[self.w2])
        self.auth.select_context(1,1)
        self.product = ProductController(self.path).save_product(dict(sku='SHIRT',name_pl='Koszula',name_en='Shirt',price='12.34',weight=1,length=10,width=10,height=10))
        self.r1 = WarehouseController(self.path).create_rack('R1',100,10)
        self.auth.select_context(1,self.w2)
        self.r2 = WarehouseController(self.path).create_rack('R1',100,10)
        WarehouseController(self.path).add_stock(self.product,self.r1,3)
        WarehouseController(self.path).add_stock(self.product,self.r2,10)
        self.person = dict(first_name='First',last_name='Last',street='Street',postal_code='00-001',city='City',country='PL',email='buyer@example.test')

    def order(self, quantity, reference='reference'):
        customers = CustomerController(self.path).get_customers()
        customer = customers[0]['customer_id'] if customers else CustomerController(self.path).save_customer(self.person)
        header = dict(channel='web',external_ref=reference,payment=1,carrier=1,package_type='CUSTOM_BOX',delivery='0',delivery_vat='0',recipient=self.person,customer_id=customer,billing={})
        return SalesController(self.path).save(header,[dict(product_id=self.product,quantity=quantity,unit='12.34',vat=23)])

    def allocate(self, order, amounts):
        picking = PickListController(self.path)
        item = picking.allocation_options([order])[0]['item_id']
        lid = picking.create_list([order],[dict(order_item_id=item,location_id=r,quantity=n) for r,n in amounts])
        return picking,lid,item

    def test_shared_reservations_private_customers_and_order_references(self):
        a = self.order(6)
        picking,lid,item = self.allocate(a,[(self.r2,6)])
        old = SalesController(self.path)
        self.auth.select_context(self.b,self.w2)
        with self.assertRaises(AuthError):
            old.details(a)
        sales = SalesController(self.path)
        self.assertEqual(sales.known_references(),set())
        with self.assertRaises(ValueError):
            sales.details(a)
        self.assertEqual(CustomerController(self.path).get_customers(),[])
        self.assertEqual(ProductController(self.path).get_products()[0]['available'],4)
        b = self.order(5)
        before = self.dump()
        with self.assertRaisesRegex(ValueError,'insufficient_available'):
            self.allocate(b,[(self.r2,5)])
        self.assertEqual(self.dump(),before)
        with self.assertRaises(AuthError):
            self.auth.select_context(self.b,1)
        with self.assertRaises(ValueError):
            WarehouseController(self.path).add_stock(self.product,self.r1,1)
        with self.assertRaises(ValueError):
            PickListController(self.path).get_list(lid)

    def dump(self):
        with closing(sqlite3.connect(self.path)) as db:
            return list(db.iterdump())

    def test_global_shortage_oldest_first_respects_assignments_and_private_feedback(self):
        older = self.order(5)
        _,old_list,_ = self.allocate(older,[(self.r2,5)])
        self.auth.select_context(self.b,self.w2)
        newer = self.order(3)
        _,new_list,_ = self.allocate(newer,[(self.r2,3)])
        uid = self.auth.create_account('worker','temporary')
        self.shop.assign_employee(uid,[self.b])
        self.auth.sign_in('worker','temporary')
        self.auth.change_password('temporary','worker-password')
        self.auth.select_context(self.b,self.w2)
        from controllers.shortage_controller import ShortageController
        ctrl = ShortageController(self.path)
        result = ctrl.reconcile(new_list,self.product,self.r2,3,'SHARED-COUNT')
        self.assertEqual(result['fulfilled'],[])
        self.assertEqual(result['cancelled'],[newer])
        self.assertTrue(result['other_shops'])
        self.assertEqual(result['affected_lists'],[new_list])
        self.assertTrue(all(a['order_id']==newer for a in result['previous_allocations']))
        before = self.dump()
        self.assertEqual(ctrl.reconcile(new_list,self.product,self.r2,3,'SHARED-COUNT'),result)
        self.assertEqual(before,self.dump())
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT status_code FROM orders WHERE order_id=?',(older,)).fetchone()[0],'NEW')
            self.assertEqual(db.execute('SELECT SUM(reserved_quantity) FROM pick_allocations WHERE order_id=?',(older,)).fetchone()[0],5)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_failure_mid_reconciliation_rolls_back_all_shops_and_history(self):
        oid = self.order(7)
        _,lid,_ = self.allocate(oid,[(self.r2,7)])
        from controllers.shortage_controller import ShortageController
        ctrl = ShortageController(self.path)
        before = self.dump()
        actual = ctrl.inventory.write_change
        calls = []
        def fail_second(*args,**kwargs):
            calls.append(1)
            if len(calls)==2:
                raise RuntimeError('injected failure')
            return actual(*args,**kwargs)
        with patch.object(ctrl.inventory,'write_change',side_effect=fail_second):
            with self.assertRaisesRegex(RuntimeError,'injected failure'):
                ctrl.reconcile(lid,self.product,self.r2,0,'FAILED')
        self.assertEqual(before,self.dump())

    def test_shortage_returns_cancelled_shops_picks_and_completes_later_order(self):
        self.shop.assign_warehouses(1,[self.w2])
        older = self.order(5)
        picking,old_list,_ = self.allocate(older,[(self.r2,5)])
        picking.start_list(old_list)
        picking.confirm_pick(picking.get_list(old_list)['lines'][0]['allocation_id'],2)
        self.auth.select_context(self.b,self.w2)
        newer = self.order(3)
        picking,new_list,_ = self.allocate(newer,[(self.r2,3)])
        picking.start_list(new_list)
        picking.confirm_pick(picking.get_list(new_list)['lines'][0]['allocation_id'],1)
        from controllers.shortage_controller import ShortageController
        result = ShortageController(self.path).reconcile(new_list,self.product,self.r2,1,'COUNT-PARTIAL')
        self.assertEqual(result['cancelled'],[older])
        self.assertEqual(result['fulfilled'],[newer])
        self.assertEqual(sum(r['quantity'] for r in result['returns']),2)
        for line in picking.get_list(new_list)['lines']:
            if line['reserved_quantity']:
                picking.confirm_pick(line['allocation_id'],line['reserved_quantity'])
        picking.close_list(new_list)
        self.assertIn(newer,DispatchController(self.path).work_orders())
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT quantity FROM inventory WHERE product_id=? AND location_id=?',(self.product,self.r2)).fetchone()[0],1)
            self.assertEqual(db.execute('SELECT status_code FROM orders WHERE order_id=?',(older,)).fetchone()[0],'CANCELLED')
            self.assertEqual(db.execute('SELECT shop_id,order_id FROM operation_history WHERE operation=\'RETURN\'').fetchone(),(1,older))

    def test_shared_transfer_rolls_back_when_other_shop_cannot_use_destination(self):
        self.auth.select_context(self.b,self.w2)
        order = self.order(8)
        self.allocate(order,[(self.r2,8)])
        self.auth.select_context(1,self.w2)
        before = self.dump()
        with self.assertRaisesRegex(sqlite3.IntegrityError,'shop_relationship_conflict'):
            WarehouseController(self.path).transfer(self.product,self.r2,self.r1,5)
        self.assertEqual(before,self.dump())

    def test_delivery_number_is_independent_for_distinct_warehouses(self):
        rows = [dict(sku='SHIRT',quantity='1',rack='R1')]
        WarehouseController(self.path).receive_delivery('DELIVERY',rows)
        self.auth.select_context(1,1)
        WarehouseController(self.path).receive_delivery('DELIVERY',rows)
        before = self.dump()
        with self.assertRaisesRegex(ValueError,'delivery_duplicate'):
            WarehouseController(self.path).receive_delivery('DELIVERY',rows)
        self.assertEqual(before,self.dump())

    def test_shared_measurement_edit_checks_unassigned_warehouse_capacity(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE locations SET max_weight=3 WHERE location_id=?',(self.r1,))
        self.auth.select_context(self.b,self.w2)
        ctrl = ProductController(self.path)
        product = ctrl.get_product(self.product)
        product['weight'] = 2
        before = self.dump()
        with self.assertRaisesRegex(ValueError,'capacity_exceeded') as error:
            ctrl.save_product(product,self.product)
        self.assertEqual(error.exception.details['location'],'')
        self.assertEqual(before,self.dump())

    def test_transfer_preserves_foreign_order_attribution_without_exposing_it(self):
        self.auth.select_context(self.b,self.w2)
        order = self.order(8)
        self.allocate(order,[(self.r2,8)])
        target = WarehouseController(self.path).create_rack('R2',100,10)
        self.auth.select_context(1,self.w2)
        operation = WarehouseController(self.path).transfer(self.product,self.r2,target,5)
        events = WarehouseController(self.path).history(operation='RESERVATION_TRANSFER')
        self.assertEqual([(e['shop_id'],e['order_id'],e['quantity']) for e in events],[(self.b,order,3)])
        uid = self.auth.create_account('worker','temporary')
        self.shop.assign_employee(uid,[1])
        self.auth.sign_in('worker','temporary')
        self.auth.change_password('temporary','worker-password')
        self.auth.select_context(1,self.w2)
        events = WarehouseController(self.path).history(operation='RESERVATION_TRANSFER')
        self.assertEqual(len(events),1)
        self.assertIsNone(events[0]['order_id'])
        self.assertIsNone(events[0]['operation_id'])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT SUM(reserved_quantity) FROM pick_allocations WHERE order_id=?',(order,)).fetchone()[0],8)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM operation_history WHERE operation_id=?',(operation,)).fetchone()[0],3)

    def test_two_shirts_and_shoes_dispatch_from_separate_warehouses_and_reopen(self):
        shoes = ProductController(self.path).save_product(dict(sku='SHOES',name_pl='Buty',name_en='Shoes',price='25',weight=1,length=10,width=10,height=10))
        WarehouseController(self.path).add_stock(shoes,self.r2,1)
        order = self.order(2,'SHIRTS-AND-SHOES')
        sales = SalesController(self.path)
        header = dict(channel='web',external_ref='SHIRTS-AND-SHOES',payment=1,carrier=1,package_type='CUSTOM_BOX',delivery='0',delivery_vat='0',recipient=self.person,customer_id=CustomerController(self.path).get_customers()[0]['customer_id'],billing={})
        sales.save(header,[dict(product_id=self.product,quantity=2,unit='12.34',vat=23),dict(product_id=shoes,quantity=1,unit='25',vat=23)],order)
        picking = PickListController(self.path)
        items = {item['product_id']:item['item_id'] for item in picking.allocation_options([order])}
        lid = picking.create_list([order],[dict(order_item_id=items[self.product],location_id=self.r1,quantity=2),dict(order_item_id=items[shoes],location_id=self.r2,quantity=1)])
        picking.start_list(lid)
        for line in picking.get_list(lid)['lines']:
            picking.confirm_pick(line['allocation_id'],line['quantity'])
        picking.close_list(lid)
        dispatch = DispatchController(self.path)
        first = dispatch.add_parcel(order,'CUSTOM_BOX',1,{items[self.product]:2},dispatch_warehouse=1)
        second = dispatch.add_parcel(order,'CUSTOM_BOX',1,{items[shoes]:1},dispatch_warehouse=self.w2)
        for shipment,tracking in ((first,'SHIRTS-TRACK'),(second,'SHOES-TRACK')):
            self.assertEqual(dispatch.confirm((f'ORD-{order:05d}',str(shipment),tracking),{},'en'),'accepted')
        self.auth.sign_out()
        reopened = AuthController(self.path)
        reopened.sign_in('admin','password')
        reopened.select_context(1,self.w2)
        with patch.object(auth_controller,'runtime',reopened):
            parcels = DispatchController(self.path).parcels(order)
            self.assertEqual({p['warehouse_id'] for p in parcels},{1,self.w2})
            self.assertEqual({p['tracking_number'] for p in parcels},{'SHIRTS-TRACK','SHOES-TRACK'})
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM orders').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT shop_id,status_code FROM orders').fetchone(),(1,'SHIPPED'))

    def test_multiwarehouse_parcels_cannot_reuse_other_warehouse_picks(self):
        order = self.order(7)
        picking,lid,item = self.allocate(order,[(self.r1,3),(self.r2,4)])
        picking.start_list(lid)
        for line in picking.get_list(lid)['lines']:
            picking.confirm_pick(line['allocation_id'],line['quantity'])
        picking.close_list(lid)
        with self.assertRaisesRegex(ValueError,'warehouse_assignment_busy'):
            self.shop.assign_warehouses(1,[self.w2])
        dispatch = DispatchController(self.path)
        before = self.dump()
        with self.assertRaisesRegex(ValueError,'excess'):
            dispatch.add_parcel(order,'CUSTOM_BOX',1,{item:7},dispatch_warehouse=1)
        self.assertEqual(before,self.dump())
        first = dispatch.add_parcel(order,'CUSTOM_BOX',1,{item:3},dispatch_warehouse=1)
        second = dispatch.add_parcel(order,'CUSTOM_BOX',1,{item:4},dispatch_warehouse=self.w2)
        self.shop.save_settings(1,{'company_info':{'name':'Shop A'}})
        self.assertEqual(dispatch.confirm((f'ORD-{order:05d}',str(first),'TRACK1'),{'name':'WRONG'},'en'),'accepted')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM invoices').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT status_code FROM orders').fetchone()[0],'PACKED')
        self.assertEqual(dispatch.confirm((f'ORD-{order:05d}',str(second),'TRACK2'),{'name':'WRONG'},'en'),'accepted')
        self.assertEqual(dispatch.confirm((f'ORD-{order:05d}',str(second),'TRACK2'),{},'en'),'duplicate')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT warehouse_id FROM packages ORDER BY package_id').fetchall(),[(1,),(self.w2,)])
            self.assertEqual(db.execute('SELECT status_code FROM orders').fetchone()[0],'SHIPPED')
            document = db.execute('SELECT document FROM invoices').fetchone()[0]
            self.assertIn('Shop A',document)
            self.assertNotIn('WRONG',document)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM invoices').fetchone()[0],1)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
        self.shop.assign_warehouses(1,[self.w2])


if __name__ == '__main__':
    unittest.main()
