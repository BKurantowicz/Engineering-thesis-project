"""Warehouse movement visibility without leaking private shop references."""
from controllers import auth_controller as auth
from controllers.auth_controller import can_admin
from controllers.shop_controller import ShopController


def history(db, since, until, operation, product, location):
    admin = can_admin()
    allowed = {s['shop_id'] for s in ShopController(auth.runtime).shops()} if auth.runtime else {1}
    rows = db.execute('''WITH events AS (
        SELECT created_at,operation,operation_id,product_id,location_id,quantity,actor_login,details,shop_id,order_id FROM operation_history
        UNION ALL SELECT t.created_at,t.transaction_type,NULL,t.product_id,t.location_id,t.quantity_change,NULL,'',NULL,NULL
        FROM inventory_transactions t WHERE NOT EXISTS(SELECT 1 FROM operation_history h WHERE h.transaction_id=t.transaction_id))
        SELECT e.*,p.sku,l.location_code,l.is_archived,l.warehouse_id,w.name AS warehouse_name
        FROM events e LEFT JOIN products p USING(product_id) LEFT JOIN locations l USING(location_id)
        LEFT JOIN physical_warehouses w USING(warehouse_id)
        WHERE (?='' OR date(e.created_at)>=?) AND (?='' OR date(e.created_at)<=?)
        AND (?='' OR e.operation=?) AND (?='' OR p.sku=?) AND (?='' OR l.location_code=?)
        AND (? OR e.location_id IN (SELECT location_id FROM scope_locations) OR e.shop_id=?)
        ORDER BY e.created_at DESC''',(since,since,until,until,operation,operation,product,product,location,location,
                                      admin,auth.runtime.shop_id if auth.runtime else 1))
    result = []
    for row in rows:
        entry = dict(row)
        if not admin and entry['shop_id'] not in allowed:
            entry.update(operation=entry['operation'].partition(':')[0],operation_id=None,actor_login=None,details='',shop_id=None,order_id=None)
        if entry['warehouse_name'] and entry['location_code']:
            entry['location_code'] = entry['warehouse_name']+' / '+entry['location_code']
        result.append(entry)
    return result
