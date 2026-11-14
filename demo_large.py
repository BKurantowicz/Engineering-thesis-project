"""Reproducible, larger mock catalogue and fulfillment history; never sends mail."""

from contextlib import closing
from datetime import datetime, timedelta
import json
import random

from controllers.customer_controller import CustomerController
from controllers.dispatch_controller import DispatchController
from controllers.inventory_controller import connect
from controllers.product_controller import ProductController
from controllers.sales_controller import SalesController
from controllers.pick_list_controller import PickListController
from controllers.capacity_controller import CapacityController


FAMILIES = (
    ("Mysz bezprzewodowa", "Wireless mouse", 79, .12, 12, 8, 5),
    ("Słuchawki", "Headphones", 159, .3, 20, 18, 8),
    ("Kamera internetowa", "Webcam", 129, .15, 12, 10, 6),
    ("Hub USB", "USB hub", 69, .1, 10, 5, 3),
    ("Dysk SSD", "SSD drive", 249, .08, 10, 7, 2),
    ("Pamięć USB", "USB flash drive", 39, .02, 6, 2, 1),
    ("Router", "Router", 199, .4, 25, 18, 6),
    ("Ładowarka USB-C", "USB-C charger", 89, .2, 10, 8, 5),
    ("Powerbank", "Power bank", 119, .35, 16, 8, 3),
    ("Podkładka pod mysz", "Mouse pad", 29, .15, 30, 25, 1),
    ("Głośnik Bluetooth", "Bluetooth speaker", 179, .6, 20, 10, 10),
    ("Mikrofon", "Microphone", 229, .5, 25, 15, 8),
    ("Statyw biurkowy", "Desk tripod", 59, .4, 25, 8, 6),
    ("Lampa biurkowa", "Desk lamp", 149, .8, 30, 18, 10),
    ("Etui na tablet", "Tablet case", 49, .25, 28, 20, 2),
    ("Torba na laptop", "Laptop bag", 139, .6, 40, 30, 5),
    ("Czytnik kart", "Card reader", 39, .05, 8, 4, 2),
    ("Adapter HDMI", "HDMI adapter", 45, .06, 8, 4, 2),
    ("Listwa zasilająca", "Power strip", 79, .5, 35, 8, 5),
)


def email_alias(inbox, number):
    if not inbox:
        return f"customer{number:03d}@example.test"
    local, separator, domain = inbox.strip().rpartition("@")
    if not separator or domain.casefold() != "gmail.com" or not local or "+" in local:
        raise ValueError("Use a plain Gmail address for the optional test inbox")
    return f"{local}+demo{number:03d}@gmail.com"


def extend_demo(db_path, test_email=None):
    """Extend the five-order fixture using the same controllers as the UI."""
    customers = CustomerController(str(db_path))
    products = ProductController(str(db_path))
    sales = SalesController(str(db_path))
    picking = PickListController(str(db_path))
    dispatch = DispatchController(str(db_path))
    rng = random.Random(20261105)
    now = datetime.now()
    first_names = ("Anna", "Piotr", "Zofia", "Jan", "Maria", "Tomasz", "Julia", "Michał", "Alicja", "Paweł")
    surnames = ("Nowak", "Kowalski", "Wiśniewska", "Wójcik", "Kowalczyk")
    cities = (("Warszawa", "00-001"), ("Kraków", "30-001"), ("Gdańsk", "80-001"),
              ("Wrocław", "50-001"), ("Poznań", "60-001"), ("Łódź", "90-001"),
              ("Katowice", "40-001"), ("Lublin", "20-001"), ("Szczecin", "70-001"), ("Częstochowa", "42-200"))
    for number in range(1, 51):
        city, postal = cities[(number - 1) % len(cities)]
        person = dict(first_name=first_names[(number - 1) % 10], last_name=surnames[(number - 1) // 10],
                      street=f"Testowa {number}", postal_code=postal, city=city,
                      email=email_alias(test_email, number), phone="")
        customers.save_customer(person, number if number <= 3 else None)
    # Rebuild only the small fixture's recipient snapshots to match these mock identities.
    with closing(connect(str(db_path))) as db, db:
        for order in db.execute("SELECT * FROM orders").fetchall():
            person = dict(customers.get_customer(order["customer_id"]))
            person["country"] = "PL"
            snapshot = json.loads(order["sales_snapshot"])
            snapshot.update(recipient=person, customer_name=f"{person['first_name']} {person['last_name']}")
            db.execute("""UPDATE orders SET sales_snapshot=?, delivery_name=?, delivery_second_name=?,
                delivery_street=?, delivery_postal_code=?, delivery_city=? WHERE order_id=?""",
                (json.dumps(snapshot, ensure_ascii=False), person["first_name"], person["last_name"],
                 person["street"], person["postal_code"], person["city"], order["order_id"]))
        db.executemany("INSERT INTO locations(location_id,location_code,max_weight,max_volume) VALUES(?,?,?,?)",
                       [(n, f"{chr(65+(n-5)//5)}-{(n-5)%5+2:02d}", 1500, 8) for n in range(5, 25)])
    catalogue, racks = [], {}
    for index in range(95):
        pl, en, price, weight, length, width, height = FAMILIES[index // 5]
        variant = index % 5 + 1
        prefix = f"200{index+1:09d}"
        check = (-sum(int(d)*(3 if i % 2 else 1) for i,d in enumerate(prefix))) % 10
        product_id = products.save_product(dict(sku=f"DEMO-{index+6:03d}", name_pl=f"{pl} M{variant}",
            name_en=f"{en} M{variant}", desc_pl="Fikcyjny produkt demonstracyjny", desc_en="Fictional demo product",
            price=f"{price+variant*10}.90", weight=str(weight), length=str(length), width=str(width), height=str(height),
            ean=prefix+str(check)))
        rack = 5 + index % 20
        products.inventory.add_stock(product_id, rack, 80 + index % 21)
        catalogue.append(product_id)
        racks[product_id] = rack
    # EANs on the original five products as well.
    for product_id in range(1, 6):
        data = products.get_product(product_id)
        prefix = f"200{product_id+95:09d}"
        data["ean"] = prefix + str((-sum(int(d)*(3 if i % 2 else 1) for i,d in enumerate(prefix))) % 10)
        products.save_product(data, product_id)
    active = [r["customer_id"] for r in customers.get_customers() if r["is_active"]]
    examples = {}
    stages = ("new", "new", "held", "cancelled", "pending", "picking", "picked", "packed", "partial_dispatch", "shipped")
    company = dict(name="DEMO Warehouse", street="Demonstracyjna 1", postal_code="00-001", city="Warszawa", country="PL")
    for index in range(295):
        customer_id = active[index % len(active)]
        person = dict(customers.get_customer(customer_id))
        person["country"] = "PL"
        selected = rng.sample(catalogue, rng.randint(2, 5))
        header = dict(customer_id=customer_id, recipient=person, billing={}, payment=1+index%3,
                      carrier=1+index%3, package_type="INPOST_C", channel=("Demo shop", "Marketplace", "B2B")[index%3],
                      external_ref=f"LARGE-{index+1:04d}", delivery="16.99", delivery_vat="23")
        lines = [dict(product_id=p, quantity=rng.randint(1, 3), unit=products.get_product(p)["price"],
                      vat=("23", "8", "5", "0")[index%4]) for p in selected]
        order_id = sales.save(header, lines)
        stage = stages[index % len(stages)]
        examples.setdefault(stage, order_id)
        stamp = (now-timedelta(days=(index*7)%90, hours=index%5)).isoformat(sep=" ", timespec="seconds")
        with closing(connect(str(db_path))) as db, db:
            db.execute("UPDATE orders SET order_date=? WHERE order_id=?", (stamp, order_id))
        if stage in ("held", "cancelled"):
            # The same pre-reservation action used by the Orders screen.
            sales.change_state(order_id, "hold" if stage == "held" else "cancel")
        if stage in ("new", "held", "cancelled"):
            continue
        _, items = sales.details(order_id)
        list_id = picking.create_list([order_id], [dict(order_item_id=i["item_id"], location_id=racks[i["product_id"]],
                                                        quantity=i["quantity"]) for i in items])
        if stage == "pending":
            continue
        picking.start_list(list_id)
        allocations = picking.get_list(list_id)["lines"]
        for line in allocations[:1] if stage == "picking" else allocations:
            picking.confirm_pick(line["allocation_id"], line["quantity"])
        if stage == "picking":
            continue
        picking.close_list(list_id)
        if stage == "picked":
            continue
        first = dispatch.add_parcel(order_id, "INPOST_C", header["carrier"], {items[0]["item_id"]:items[0]["quantity"]})
        second = dispatch.add_parcel(order_id, "INPOST_C", header["carrier"], {i["item_id"]:i["quantity"] for i in items[1:]})
        if stage == "packed":
            continue
        for shipment in (first, second) if stage == "shipped" else (first,):
            dispatch.confirm((f"ORD-{order_id:05d}", str(shipment), f"DEMO-TRACK-{shipment:06d}"), company, "pl")
    # Fail before replacing the designated database if an invariant is broken.
    with closing(connect(str(db_path))) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Invalid demonstration database")
        if any(r["reserved"] > r["quantity"] for r in products.inventory.stock_snapshot(db)):
            raise ValueError("Demonstration reservations exceed stock")
    if any(r[m]["percentage"] > 100 for r in CapacityController(str(db_path)).get_capacity()["racks"] for m in ("weight", "volume")):
        raise ValueError("Demonstration rack capacity exceeded")
    return {"examples": examples, "products": 100, "customers": 50, "orders": 300}
