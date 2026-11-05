"""Transactional sale entry, monetary snapshots and order lifecycle."""
import json
from contextlib import closing
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from controllers.customer_controller import CustomerController
from controllers.inventory_controller import connect

CENT = Decimal("0.01")


def amount(value, field):
    try:
        result = Decimal(str(value).replace(",", "."))
        if not result.is_finite() or result < 0 or result > Decimal("9999999999") or result != result.quantize(CENT):
            raise ValueError
    except (InvalidOperation, ValueError):
        raise ValueError(field) from None
    return result


def priced_line(quantity, unit, vat):
    if not str(quantity).isascii() or not str(quantity).isdigit() or not 0 < int(quantity) <= 2147483647:
        raise ValueError("quantity")
    price = amount(unit, "price")
    rate = amount(vat, "vat")
    if rate > 100:
        raise ValueError("vat")
    gross = price * int(quantity)
    net = (gross / (1 + rate / 100)).quantize(CENT, ROUND_HALF_UP)
    return dict(quantity=int(quantity), unit=str(price), vat=str(rate), gross_cents=int(gross*100),
                net_cents=int(net*100), vat_cents=int((gross-net)*100))


class SalesController:
    def __init__(self, db_path):
        self.db_path = db_path

    def choices(self):
        with closing(connect(self.db_path)) as db:
            return {key: [dict(r) for r in db.execute(query)] for key, query in {
                "customers": "SELECT * FROM customers WHERE is_active=1 ORDER BY last_name, first_name",
                "products": "SELECT * FROM products WHERE is_active=1 ORDER BY sku",
                "payments": "SELECT * FROM dict_payment_methods ORDER BY id",
                "carriers": "SELECT * FROM dict_shipping_methods ORDER BY shipping_id",
                "types": "SELECT * FROM dict_package_types ORDER BY base_cost",
            }.items()}

    @staticmethod
    def editable(db, order_id):
        row = db.execute("""SELECT * FROM orders WHERE order_id=? AND status_code='NEW'
            AND NOT EXISTS (SELECT 1 FROM pick_list_orders WHERE order_id=orders.order_id)""", (order_id,)).fetchone()
        if row is None:
            raise ValueError("order_locked")
        return row

    def change_state(self, order_id, action):
        with closing(connect(self.db_path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            self.editable(db, order_id)
            if action == "cancel":
                db.execute("UPDATE orders SET status_code='CANCELLED',held=0 WHERE order_id=?", (order_id,))
            elif action in ("hold", "resume"):
                db.execute("UPDATE orders SET held=? WHERE order_id=?", (int(action == "hold"), order_id))
            else:
                raise ValueError("action")

    def details(self, order_id):
        with closing(connect(self.db_path)) as db:
            row = db.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
            if row is None:
                raise ValueError("order")
            items = db.execute("SELECT * FROM order_items WHERE order_id=? ORDER BY item_id", (order_id,))
            return dict(row), [dict(i) for i in items]

    def save(self, header, lines, order_id=None, new_customer=None, importing=False):
        with closing(connect(self.db_path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            previous_header = {}
            if order_id is not None:
                previous_header = json.loads(self.editable(db, order_id)["sales_snapshot"] or "{}")
            channel = header.get("channel", "").strip()
            reference = header.get("external_ref", "").strip()
            if not channel or importing and not reference:
                raise ValueError("identity")
            db.create_function("casefold", 1, lambda value: (value or "").strip().casefold())
            if reference and db.execute("""SELECT 1 FROM orders WHERE casefold(channel)=?
                    AND casefold(external_ref)=? AND order_id != ?""",
                    (channel.casefold(), reference.casefold(), order_id or -1)).fetchone():
                raise ValueError("duplicate")
            customer_id = header.get("customer_id")
            if new_customer is not None:
                values = CustomerController.validate(new_customer)
                email = (values["email"] or "").casefold()
                matches = [r[0] for r in db.execute("SELECT customer_id,email FROM customers WHERE email IS NOT NULL")
                           if email and r[1].casefold() == email]
                if len(matches) > 1:
                    raise ValueError("customer")
                if matches:
                    customer_id = matches[0]
                else:
                    fields = CustomerController.FIELDS
                    customer_id = db.execute(f"INSERT INTO customers ({','.join(fields)}) VALUES (?,?,?,?,?,?,?)",
                                             tuple(values[k] for k in fields)).lastrowid
            customer = db.execute("SELECT * FROM customers WHERE customer_id=? AND is_active=1", (customer_id,)).fetchone()
            if customer is None:
                raise ValueError("customer")
            recipient = CustomerController.validate(header["recipient"])
            recipient["country"] = header["recipient"].get("country", "").strip()
            if not recipient["country"]:
                raise ValueError("country")
            for table, key, field in (("dict_payment_methods","id","payment"), ("dict_shipping_methods","shipping_id","carrier"),
                                      ("dict_package_types","package_code","package_type")):
                if not db.execute(f"SELECT 1 FROM {table} WHERE {key}=?", (header.get(field),)).fetchone():
                    raise ValueError(field)
            delivery = priced_line(1, header["delivery"], header["delivery_vat"])
            original = {r["item_id"]: r for r in db.execute(
                "SELECT item_id, product_id, sale_snapshot FROM order_items WHERE order_id=?", (order_id,))}
            snapshots = []
            for item in lines:
                product = db.execute("SELECT * FROM products WHERE product_id=? AND is_active=1", (item["product_id"],)).fetchone()
                if not product:
                    raise ValueError("product")
                saved = priced_line(item["quantity"], item["unit"], item["vat"])
                prior = original.pop(item.get("item_id"), None)
                if item.get("item_id") is not None and (not prior or prior["product_id"] != product["product_id"]):
                    raise ValueError("product")
                source = json.loads(prior["sale_snapshot"]) if prior and prior["sale_snapshot"] else product
                saved.update({k: source[k] for k in ("product_id","sku","name_pl","name_en","weight")})
                snapshots.append(saved)
            if not snapshots:
                raise ValueError("basket")
            net = sum(line["net_cents"] for line in snapshots) + delivery["net_cents"]
            gross = sum(line["gross_cents"] for line in snapshots) + delivery["gross_cents"]
            if gross > 999999999999999:
                raise ValueError("price")
            snapshot = dict(header, recipient=recipient, customer_id=customer_id, delivery_line=delivery,
                            customer_name=f"{customer['first_name']} {customer['last_name']}")
            if previous_header.get("customer_id") == customer_id:
                snapshot["customer_name"] = previous_header.get("customer_name", snapshot["customer_name"])
            values = dict(customer_id=customer_id, payment_method_id=header["payment"], total_amount=gross/100,
                          delivery_name=recipient["first_name"], delivery_second_name=recipient["last_name"],
                          delivery_street=recipient["street"], delivery_postal_code=recipient["postal_code"],
                          delivery_city=recipient["city"], channel=channel, external_ref=reference or None,
                          sales_snapshot=json.dumps(snapshot, ensure_ascii=False), net_cents=net, delivery_cents=delivery["gross_cents"])
            if order_id is None:
                keys = ",".join(values)
                order_id = db.execute(f"INSERT INTO orders ({keys}) VALUES ({','.join('?' for _ in values)})",
                                      tuple(values.values())).lastrowid
            else:
                db.execute(f"UPDATE orders SET {','.join(k+'=?' for k in values)} WHERE order_id=?",
                           (*values.values(), order_id))
                db.execute("DELETE FROM order_items WHERE order_id=?", (order_id,))
            db.executemany("INSERT INTO order_items (order_id,product_id,quantity,unit_price,sale_snapshot) VALUES (?,?,?,?,?)",
                           [(order_id,i["product_id"],i["quantity"],float(i["unit"]),json.dumps(i, ensure_ascii=False)) for i in snapshots])
            return order_id
