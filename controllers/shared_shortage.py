"""Global stock reconciliation with private shop feedback and warehouse-aware plans."""
from collections import defaultdict
from contextlib import closing
import json
import sqlite3

from controllers.auth_controller import require_access, can_admin
from controllers.inventory_controller import WarehouseError
from controllers.shop_scope import shop_id


def private_result(db, result):
    if can_admin():
        return result
    sid = shop_id()
    orders = {r[0] for r in db.execute('SELECT order_id FROM orders WHERE shop_id=?',(sid,))}
    lists = {r[0] for r in db.execute('SELECT pick_list_id FROM pick_lists WHERE shop_id=?',(sid,))}
    allowed_locations = {r[0] for r in db.execute('''SELECT location_id FROM locations JOIN shop_warehouses USING(warehouse_id)
        WHERE shop_id=?''',(sid,))}
    return dict(result,
        fulfilled=[oid for oid in result['fulfilled'] if oid in orders],
        cancelled=[oid for oid in result['cancelled'] if oid in orders],
        affected_lists=[lid for lid in result['affected_lists'] if lid in lists],
        previous_allocations=[a for a in result['previous_allocations'] if a['order_id'] in orders],
        returns=[r for r in result['returns'] if r['location_id'] in allowed_locations],
        other_shops=any(oid not in orders for oid in result['fulfilled']+result['cancelled']))


def reconcile(controller, list_id, product_id, location_id, actual_quantity, operation_id, recorded_quantity):
    # This internal transaction is intentionally global. Authorization is checked
    # against its initiating list/location before touching any shared reservations.
    with closing(sqlite3.connect(controller.db_path)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        require_access(controller)
        sid = shop_id()
        permitted = db.execute('''SELECT 1 FROM pick_lists p JOIN shop_warehouses sw ON sw.shop_id=p.shop_id
            JOIN locations l ON l.warehouse_id=sw.warehouse_id WHERE p.pick_list_id=? AND p.shop_id=? AND l.location_id=?''',
            (list_id,sid,location_id)).fetchone()
        if not permitted:
            raise WarehouseError('shop_forbidden')
        previous = db.execute('SELECT * FROM shortage_events WHERE operation_id=?',(operation_id,)).fetchone()
        if previous:
            if (previous['pick_list_id'],previous['product_id'],previous['source_location_id'],previous['actual_quantity']) != (list_id,product_id,location_id,actual_quantity):
                raise WarehouseError('operation_conflict')
            return private_result(db,json.loads(previous['result_json']))
        if not db.execute("SELECT 1 FROM pick_lists WHERE pick_list_id=? AND status IN ('PENDING','IN_PROGRESS')",(list_id,)).fetchone():
            raise WarehouseError('list_not_open')
        if not db.execute('SELECT 1 FROM pick_allocations WHERE pick_list_id=? AND product_id=? AND location_id=?',(list_id,product_id,location_id)).fetchone():
            raise WarehouseError('allocation_not_found')
        location = db.execute('SELECT * FROM locations WHERE location_id=?',(location_id,)).fetchone()
        if not location or controller.inventory.capacity.is_virtual(location):
            raise WarehouseError('physical_location_required')
        stock = db.execute('SELECT quantity FROM inventory WHERE product_id=? AND location_id=?',(product_id,location_id)).fetchone()
        if stock and recorded_quantity is not None and recorded_quantity != stock[0]:
            raise WarehouseError('stock_changed')
        if not stock or type(stock[0]) is not int or actual_quantity >= stock[0]:
            raise WarehouseError('no_shortage')
        missing = stock[0]-actual_quantity
        db.execute('CREATE TEMP VIEW scope_locations AS SELECT *,location_code AS display_code FROM locations')
        db.execute('CREATE TEMP VIEW scope_products AS SELECT * FROM products')
        affected = {list_id} | {r[0] for r in db.execute('''SELECT DISTINCT a.pick_list_id FROM pick_allocations a
            JOIN pick_lists p USING(pick_list_id) WHERE a.product_id=? AND a.location_id=?
            AND a.reserved_quantity>0 AND p.status IN ('PENDING','IN_PROGRESS')''',(product_id,location_id))}
        marks = ','.join('?' for _ in affected)
        orders = [dict(r) for r in db.execute(f'''SELECT DISTINCT o.* FROM orders o JOIN pick_list_orders po USING(order_id)
            WHERE po.pick_list_id IN ({marks}) AND o.status_code IN ('NEW','IN_PROGRESS')
            ORDER BY datetime(o.order_date),o.order_id''',tuple(sorted(affected)))]
        ids = [o['order_id'] for o in orders]
        marks = ','.join('?' for _ in ids)
        allocations = [dict(r) for r in db.execute(f'SELECT * FROM pick_allocations WHERE order_id IN ({marks}) ORDER BY allocation_id',ids)]
        items = [dict(r) for r in db.execute(f'SELECT * FROM order_items WHERE order_id IN ({marks}) ORDER BY item_id',ids)]
        warehouses = {r[0]:r[1] for r in db.execute('SELECT location_id,warehouse_id FROM locations')}
        assignments = defaultdict(set)
        for shop,warehouse in db.execute('SELECT shop_id,warehouse_id FROM shop_warehouses'):
            assignments[shop].add(warehouse)
        lists = {o['order_id']: db.execute('''SELECT p.pick_list_id FROM pick_list_orders po JOIN pick_lists p USING(pick_list_id)
            WHERE po.order_id=? AND p.status IN ('PENDING','IN_PROGRESS') ORDER BY p.pick_list_id LIMIT 1''',(o['order_id'],)).fetchone()[0] for o in orders}
        controller.inventory.write_change(db,product_id,location_id,-missing,'SHORTAGE:'+operation_id)
        if ids:
            db.execute(f'UPDATE pick_allocations SET reserved_quantity=0 WHERE order_id IN ({marks})',ids)
        supplies = []
        for row in controller.inventory.stock_snapshot(db):
            supplies.append(dict(product=row['product_id'],warehouse=warehouses[row['location_id']],
                location=row['location_id'],quantity=row['available'],owner=None,item=None,allocation=None))
        for row in allocations:
            held = row['picked_quantity']-row['returned_quantity']
            if held:
                supplies.append(dict(product=row['product_id'],warehouse=warehouses[row['location_id']],
                    location=row['location_id'],quantity=held,owner=row['order_id'],item=row['order_item_id'],allocation=row['allocation_id']))
        available = [s['quantity'] for s in supplies]
        retained = defaultdict(int)
        reservations = defaultdict(int)
        fulfilled, cancelled = [], []
        for order in orders:
            oid = order['order_id']
            trial = available.copy()
            planned = []
            order_items = [i for i in items if i['order_id']==oid]
            possible = bool(order_items)
            for item in order_items:
                controller.inventory.positive_quantity(item['quantity'])
                remaining = item['quantity']
                candidates = [idx for idx,s in enumerate(supplies) if s['product']==item['product_id'] and s['warehouse'] in assignments[order['shop_id']]]
                candidates.sort(key=lambda idx:(
                    not (supplies[idx]['owner']==oid and supplies[idx]['item']==item['item_id']),
                    supplies[idx]['owner'] is not None,supplies[idx]['warehouse'],supplies[idx]['location'],idx))
                for idx in candidates:
                    take = min(remaining,trial[idx])
                    if take:
                        trial[idx] -= take
                        remaining -= take
                        planned.append((item,idx,take))
                    if not remaining:
                        break
                if remaining:
                    possible = False
                    break
            if not possible:
                cancelled.append(oid)
                continue
            available = trial
            fulfilled.append(oid)
            for item,idx,quantity in planned:
                source = supplies[idx]
                if source['owner']==oid and source['item']==item['item_id']:
                    retained[source['allocation']] += quantity
                else:
                    reservations[oid,item['item_id'],item['product_id'],source['warehouse']] += quantity
        returns = []
        for row in allocations:
            quantity = row['picked_quantity']-row['returned_quantity']-retained[row['allocation_id']]
            if quantity:
                returns.extend(_return_stock(controller,db,row['product_id'],row['location_id'],quantity,operation_id,row['order_id']))
            db.execute('UPDATE pick_allocations SET returned_quantity=returned_quantity+?,cancelled=1 WHERE allocation_id=?',(quantity,row['allocation_id']))
        db.execute("INSERT OR IGNORE INTO dict_order_statuses VALUES('CANCELLED','Anulowane','Cancelled')")
        db.executemany("UPDATE orders SET status_code='CANCELLED',cancellation_reason=? WHERE order_id=?",[('SHORTAGE:'+operation_id,oid) for oid in cancelled])
        free = controller.inventory.stock_snapshot(db)
        for (oid,item,pid,wid),quantity in reservations.items():
            for row in free:
                if row['product_id']!=pid or warehouses[row['location_id']]!=wid:
                    continue
                take = min(quantity,row['available'])
                if take:
                    db.execute('''INSERT INTO pick_allocations(pick_list_id,order_id,order_item_id,product_id,location_id,quantity,reserved_quantity)
                        VALUES(?,?,?,?,?,?,?)''',(lists[oid],oid,item,pid,row['location_id'],take,take))
                    row['available'] -= take
                    quantity -= take
                if not quantity:
                    break
            if quantity:
                raise WarehouseError('insufficient_available')
        virtual = db.execute("SELECT location_id FROM locations WHERE warehouse_id=? AND lower(trim(location_code))='braki'",(location['warehouse_id'],)).fetchone()
        if virtual:
            virtual_id = virtual[0]
        else:
            virtual_id = db.execute("INSERT INTO locations(location_code,max_weight,max_volume,is_virtual,warehouse_id) VALUES('braki',0,0,1,?)",(location['warehouse_id'],)).lastrowid
        controller.inventory.write_change(db,product_id,virtual_id,missing,'MISSING:'+operation_id)
        result = dict(fulfilled=fulfilled,cancelled=cancelled,affected_lists=sorted(affected),missing_quantity=missing,
                      returns=returns,previous_allocations=allocations)
        db.execute('INSERT INTO shortage_events VALUES(?,?,?,?,?,?,?,CURRENT_TIMESTAMP)',
                   (operation_id,list_id,product_id,location_id,missing,actual_quantity,json.dumps(result)))
        require_access(controller)
        return private_result(db,result)


def _return_stock(controller, db, product, preferred, quantity, operation, order_id):
    """Return to physical racks in the source warehouse, never consolidate stock."""
    wid = db.execute('SELECT warehouse_id FROM locations WHERE location_id=?',(preferred,)).fetchone()[0]
    db.execute('DROP VIEW scope_locations')
    db.execute(f'CREATE TEMP VIEW scope_locations AS SELECT *,location_code AS display_code FROM locations WHERE warehouse_id={int(wid)}')
    try:
        return controller.return_stock(db,product,preferred,quantity,operation,order_id=order_id)
    finally:
        db.execute('DROP VIEW scope_locations')
        db.execute('CREATE TEMP VIEW scope_locations AS SELECT *,location_code AS display_code FROM locations')
