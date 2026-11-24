"""Pack already picked goods and reconcile carrier confirmations by dispatch ID."""
from controllers.auth_controller import reading
from controllers.auth_controller import authorized, bind
import csv
import json
import os
import re
from contextlib import closing
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from controllers.inventory_controller import connect
from controllers.pick_list_controller import PickListController
from controllers.shop_scope import is_unified, insert, warehouse_id, settings_for_order


class DispatchController:
    def __init__(self, db_path):
        self.db_path = db_path
        bind(self)

    @staticmethod
    def eligible(db, order_id):
        order = db.execute("SELECT * FROM scope_orders WHERE order_id=?", (order_id,)).fetchone()
        if not order or order["status_code"]!="IN_PROGRESS" or order["held"]:
            return False
        open_list = db.execute("""SELECT 1 FROM scope_pick_list_orders JOIN scope_pick_lists USING(pick_list_id)
                                  WHERE order_id=? AND status!='CLOSED'""",(order_id,)).fetchone()
        return not open_list and PickListController.order_fulfilled(db,order_id)

    @reading
    def work_orders(self):
        with closing(connect(self.db_path)) as db:
            return [r[0] for r in db.execute("SELECT order_id FROM scope_orders WHERE status_code IN ('IN_PROGRESS','PACKED') ORDER BY order_id")
                    if self.eligible(db,r[0]) or db.execute("SELECT 1 FROM scope_order_shipments WHERE order_id=? AND package_id IS NOT NULL",(r[0],)).fetchone()]

    @staticmethod
    def items(db, order_id):
        return [dict(r) for r in db.execute("""SELECT i.*,p.sku,p.ean,p.weight,p.name_en,p.name_pl,
            i.quantity-COALESCE((SELECT SUM(pc.quantity) FROM parcel_contents pc WHERE pc.item_id=i.item_id),0) AS remaining
            FROM scope_order_items i JOIN scope_products p USING(product_id) WHERE i.order_id=? ORDER BY i.item_id""",(order_id,))]

    @reading
    def packing_lines(self, order_id, dispatch_warehouse=None):
        with closing(connect(self.db_path)) as db:
            return self.warehouse_items(db,order_id,dispatch_warehouse)

    @classmethod
    def warehouse_items(cls, db, order_id, dispatch_warehouse=None):
        items = cls.items(db,order_id)
        if not items:
            return []
        if not is_unified(db):
            return items
        wid = dispatch_warehouse if dispatch_warehouse is not None else warehouse_id()
        if wid is None or not db.execute('''SELECT 1 FROM scope_orders o JOIN shop_warehouses sw USING(shop_id)
                WHERE o.order_id=? AND sw.warehouse_id=?''', (order_id,wid)).fetchone():
            raise ValueError('warehouse_forbidden')
        for item in items:
            picked = db.execute('''SELECT COALESCE(SUM(a.picked_quantity-a.returned_quantity),0)
                FROM scope_pick_allocations a JOIN scope_locations l USING(location_id)
                WHERE a.order_item_id=? AND l.warehouse_id=?''', (item['item_id'],wid)).fetchone()[0]
            packed = db.execute('''SELECT COALESCE(SUM(pc.quantity),0) FROM parcel_contents pc
                JOIN scope_packages p USING(package_id) WHERE pc.item_id=? AND p.warehouse_id=?''', (item['item_id'],wid)).fetchone()[0]
            item['remaining'] = min(item['remaining'],picked-packed)
            item['warehouse_id'] = wid
        return items

    @authorized()
    def add_parcel(self, order_id, package_type, carrier_id, counts, token=None, dispatch_warehouse=None):
        with closing(connect(self.db_path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if token:
                existing=db.execute("SELECT shipment_id FROM scope_order_shipments WHERE order_id=? AND packing_token=?",(order_id,token)).fetchone()
                if existing:
                    return existing[0]
            if not self.eligible(db,order_id):
                raise ValueError("packing_locked")
            if not counts or any(type(n) is not int or n<=0 for n in counts.values()):
                raise ValueError("quantity")
            box = db.execute("SELECT * FROM dict_package_types WHERE package_code=?",(package_type,)).fetchone()
            if not box or not db.execute("SELECT 1 FROM dict_shipping_methods WHERE shipping_id=?",(carrier_id,)).fetchone():
                raise ValueError("carrier")
            items = {i["item_id"]:i for i in self.warehouse_items(db,order_id,dispatch_warehouse)}
            if any(k not in items or n>items[k]["remaining"] for k,n in counts.items()):
                raise ValueError("excess")
            weights = [items[k]["weight"] for k in counts]
            weight = sum(items[k]["weight"]*n for k,n in counts.items()) if all(w and w>0 for w in weights) else None
            if weight is not None and weight>box["max_weight"]:
                raise ValueError("parcel_weight")
            values = dict(order_id=order_id,package_code=package_type,actual_weight=weight)
            if is_unified(db):
                values['warehouse_id'] = dispatch_warehouse if dispatch_warehouse is not None else warehouse_id()
            parcel = insert(db, 'packages', values).lastrowid
            db.executemany("INSERT INTO parcel_contents VALUES(?,?,?)",[(parcel,k,n) for k,n in counts.items()])
            dispatch = db.execute("""INSERT INTO order_shipments(order_id,shipping_type_id,package_code,final_shipping_cost,package_id,packing_token)
                        VALUES(?,?,?,?,?,?)""",(order_id,carrier_id,package_type,box["base_cost"],parcel,token)).lastrowid
            if all(i["remaining"]==0 for i in self.items(db,order_id)):
                db.execute("UPDATE orders SET status_code='PACKED' WHERE order_id=?",(order_id,))
            return dispatch

    @reading
    def parcels(self, order_id=None):
        with closing(connect(self.db_path)) as db:
            rows = db.execute("""SELECT s.*,p.actual_weight,c.carrier_name,o.status_code,o.sales_snapshot,o.delivery_name,
                o.delivery_second_name,o.delivery_street,o.delivery_city,o.delivery_postal_code,m.state AS mail_state,m.detail AS mail_detail
                FROM scope_order_shipments s JOIN scope_packages p USING(package_id) JOIN scope_orders o ON o.order_id=s.order_id
                JOIN dict_shipping_methods c ON c.shipping_id=s.shipping_type_id LEFT JOIN scope_dispatch_mail m USING(shipment_id)
                WHERE (? IS NULL OR s.order_id=?) ORDER BY s.shipment_id""",(order_id,order_id))
            results = []
            for row in rows:
                contents = db.execute("""SELECT COALESCE(json_extract(i.sale_snapshot,'$.sku'),p.sku),pc.quantity
                    FROM parcel_contents pc JOIN scope_order_items i USING(item_id) JOIN scope_products p USING(product_id)
                    WHERE pc.package_id=? ORDER BY pc.item_id""",(row["package_id"],))
                parcel = dict(row,contents=", ".join(f"{sku} × {qty}" for sku,qty in contents))
                if is_unified(db):
                    warehouse = db.execute('''SELECT p.warehouse_id,w.name FROM scope_packages p
                        JOIN physical_warehouses w USING(warehouse_id) WHERE p.package_id=?''',(row['package_id'],)).fetchone()
                    parcel.update(warehouse_id=warehouse[0],warehouse_name=warehouse[1])
                results.append(parcel)
            return results

    @authorized()
    def export(self, ids, folder):
        ready = [r for r in self.parcels() if r["shipment_id"] in ids and r["status_code"]=="PACKED" and not r["dispatched_at"]]
        if not ready or len(ready)!=len(set(ids)):
            raise ValueError("not_ready")
        directory = Path(folder)
        directory.mkdir(exist_ok=True,parents=True)
        files = []
        for carrier in sorted({r["carrier_name"] for r in ready}):
            selected = [r for r in ready if r["carrier_name"]==carrier]
            slug = re.sub(r"[^\w-]","_",carrier)
            path = directory/f"{slug}-{selected[0]['shipment_id']}-{selected[-1]['shipment_id']}.csv"
            with NamedTemporaryFile(mode="w",encoding="utf-8-sig",newline="",dir=directory,delete=False) as f:
                temp = Path(f.name)
                try:
                    writer=csv.writer(f,delimiter=";")
                    writer.writerow(("order_ref","dispatch_id","carrier","recipient","street","postal_code","city","country",
                                     "email","phone","package_type","contents","weight_kg"))
                    for r in selected:
                        person = json.loads(r["sales_snapshot"] or "{}").get("recipient",{})
                        writer.writerow((f"ORD-{r['order_id']:05d}",r["shipment_id"],carrier,
                            " ".join(filter(None,(r["delivery_name"],r["delivery_second_name"]))),r["delivery_street"],
                            r["delivery_postal_code"],r["delivery_city"],person.get("country"),person.get("email"),person.get("phone"),
                            r["package_code"],r["contents"],r["actual_weight"] if r["actual_weight"] is not None else "N/A"))
                except BaseException:
                    f.close()
                    temp.unlink(missing_ok=True)
                    raise
            try:
                os.replace(temp,path)
            finally:
                temp.unlink(missing_ok=True)
            files.append(path)
        return files

    @staticmethod
    def check(db, order_ref, dispatch_id, tracking):
        match = re.fullmatch(r"ORD-(\d+)",order_ref.strip(),re.I)
        if not match or not re.fullmatch(r"[0-9]{1,18}",dispatch_id.strip()) or not tracking.strip():
            raise ValueError("file_format")
        row = db.execute("""SELECT s.*,o.status_code,o.sales_snapshot FROM scope_order_shipments s JOIN scope_orders o USING(order_id)
                           WHERE shipment_id=? AND package_id IS NOT NULL""",(int(dispatch_id),)).fetchone()
        if not row or int(match[1])!=row["order_id"]:
            raise ValueError("wrong_parcel")
        if row["dispatched_at"]:
            if row["tracking_number"]==tracking:
                return row,"duplicate"
            raise ValueError("tracking_conflict")
        if row["status_code"]!="PACKED":
            raise ValueError("not_ready")
        if db.execute("SELECT 1 FROM scope_order_shipments WHERE tracking_number=?",(tracking,)).fetchone() or db.execute(
                "SELECT 1 FROM scope_packages WHERE tracking_number=?",(tracking,)).fetchone():
            raise ValueError("tracking_conflict")
        return row,"ready"

    @reading
    def preview(self,path):
        with open(path,encoding="utf-8-sig",newline="") as f:
            reader=csv.DictReader(f,delimiter=";")
            if not {"order_ref","dispatch_id","tracking"}.issubset(reader.fieldnames or []):
                raise ValueError("file_format")
            rows = [tuple((r[k] or "").strip() for k in ("order_ref","dispatch_id","tracking")) for r in reader]
        by_dispatch,by_tracking={},{}
        for ref,d,t in rows:
            key = d.lstrip("0") or "0"
            order_key = ref.upper().removeprefix("ORD-").lstrip("0") or "0"
            by_dispatch.setdefault(key,set()).add((order_key,t))
            by_tracking.setdefault(t,set()).add(key)
        result,seen=[],set()
        with closing(connect(self.db_path)) as db:
            for record in rows:
                ref,d,t=record
                try:
                    _,state=self.check(db,*record)
                    key = d.lstrip("0") or "0"
                    if len(by_dispatch[key])>1 or len(by_tracking[t])>1:
                        state="tracking_conflict"
                    elif (key,t) in seen:
                        state="duplicate"
                except ValueError as error:
                    state=str(error)
                result.append((record,state))
                seen.add((d.lstrip("0") or "0",t))
        return result

    @authorized()
    def confirm(self,record,company,lang):
        with closing(connect(self.db_path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row,state=self.check(db,*record)
            if state=="duplicate":
                return state
            tracking=record[2]
            stamp=datetime.now().isoformat(sep=" ",timespec="seconds")
            db.execute("UPDATE order_shipments SET tracking_number=?,dispatched_at=? WHERE shipment_id=?",(tracking,stamp,row["shipment_id"]))
            db.execute("UPDATE packages SET tracking_number=? WHERE package_id=?",(tracking,row["package_id"]))
            remaining=db.execute("SELECT 1 FROM scope_order_shipments WHERE order_id=? AND package_id IS NOT NULL AND dispatched_at IS NULL",(row["order_id"],)).fetchone()
            header=json.loads(row["sales_snapshot"] or "{}")
            invoice_id=None
            if not remaining:
                lines=[json.loads(i["sale_snapshot"] or "{}") for i in self.items(db,row["order_id"])]
                if not header.get("delivery_line") or any("net_cents" not in i for i in lines):
                    raise ValueError("settlement_required")
                number=f"FV/{stamp[:4]}/{stamp[5:7]}/{row['order_id']}"
                if is_unified(db):
                    shop = db.execute('SELECT shop_id FROM scope_orders WHERE order_id=?',(row['order_id'],)).fetchone()[0]
                    db.execute('''INSERT INTO invoice_sequences(shop_id,year,next_number) VALUES(?,?,2)
                        ON CONFLICT(shop_id,year) DO UPDATE SET next_number=next_number+1''',(shop,int(stamp[:4])))
                    sequence = db.execute('SELECT next_number-1 FROM invoice_sequences WHERE shop_id=? AND year=?',(shop,int(stamp[:4]))).fetchone()[0]
                    number = f'SHOP-{shop}/{stamp[:4]}/{sequence:06d}'
                    company = settings_for_order(db,row['order_id']).get('company_info',{})
                document=dict(number=number,date=stamp,order_id=row["order_id"],seller=company,recipient=header["recipient"],
                              billing=header.get("billing",{}),lines=lines,delivery=header["delivery_line"])
                invoice_id=insert(db,'invoices',dict(order_id=row['order_id'],invoice_number=number,
                    issue_date=stamp,document=json.dumps(document,ensure_ascii=False))).lastrowid
                db.execute("UPDATE orders SET status_code='SHIPPED' WHERE order_id=?",(row["order_id"],))
            email=header.get("recipient",{}).get("email")
            if is_unified(db):
                company = settings_for_order(db,row['order_id']).get('company_info',{})
            carrier=db.execute("SELECT carrier_name FROM dict_shipping_methods WHERE shipping_id=?",(row["shipping_type_id"],)).fetchone()[0]
            message=dict(order=f"ORD-{row['order_id']:05d}",carrier=carrier,tracking=tracking,lang=lang,seller=company)
            db.execute("INSERT INTO dispatch_mail(shipment_id,recipient,message,invoice_id,state) VALUES(?,?,?,?,?)",
                       (row["shipment_id"],email,json.dumps(message),invoice_id,"pending" if email else "no_email"))
            return "accepted"
