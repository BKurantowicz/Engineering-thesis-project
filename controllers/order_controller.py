import sqlite3
from contextlib import closing
from datetime import datetime, timedelta

class OrderValidationError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code

class OrderController:
    def __init__(self, db_path="warehouse.db"):
        self.db_path = db_path

    def get_orders(self, limit=50, date_filter="", search_term="", sort_by="date_desc", *, identity="", destination="", product="", channel="", detailed=False):
        """
        Fetches a list of orders from the database, applying date filters, 
        text search, and including the new address columns introduced in PR 1.
        """
        limit = limit if limit is not None else 50
        date_filter = str(date_filter) if date_filter is not None else ""
        
        query = """
            SELECT 
                o.order_id, 
                o.order_date, 
                o.status_code, 
                o.total_amount, 
                c.first_name, 
                c.last_name, 
                pm.name_pl as payment, 
                sh.package_code, 
                sh.tracking_number,
                o.delivery_name,
                o.delivery_second_name,
                o.delivery_street,
                o.delivery_postal_code,
                o.delivery_city
            FROM orders o
            LEFT JOIN customers c ON o.customer_id = c.customer_id
            LEFT JOIN dict_payment_methods pm ON o.payment_method_id = pm.id
            LEFT JOIN order_shipments sh ON sh.shipment_id = (SELECT MIN(shipment_id) FROM order_shipments WHERE order_id=o.order_id)
            WHERE 1=1
        """
        
        if detailed:
            query = query.replace("o.delivery_city\n", """o.delivery_city, o.channel, o.external_ref, o.sales_snapshot,
                o.net_cents, o.delivery_cents, o.held, sh.final_shipping_cost, pm.name_en AS payment_en,
                (SELECT COUNT(*) FROM order_shipments WHERE order_id=o.order_id AND package_id IS NOT NULL) AS parcel_count,
                (SELECT COUNT(*) FROM order_shipments WHERE order_id=o.order_id AND dispatched_at IS NOT NULL) AS sent_count,
                (SELECT MAX(dispatched_at) FROM order_shipments WHERE order_id=o.order_id) AS dispatched_at
            """, 1)
        params = []
        for term, columns in (
            (identity, ["printf('ORD-%05d',o.order_id)", "o.status_code", "o.external_ref", "c.first_name || ' ' || c.last_name",
                        "json_extract(o.sales_snapshot,'$.customer_name')"]),
            (destination, ["o.delivery_name","o.delivery_second_name","o.delivery_street","o.delivery_postal_code","o.delivery_city",
                           "c.first_name || ' ' || c.last_name"]),
        ):
            if term:
                query += " AND (" + " OR ".join("instr(fold("+col+"),?)>0" for col in columns) + ")"
                params.extend([term.casefold()] * len(columns))
        if channel:
            query += " AND fold(o.channel)=?"
            params.append(channel.strip().casefold())
        if product:
            query += """ AND EXISTS (SELECT 1 FROM order_items i JOIN products p USING(product_id)
                        WHERE i.order_id=o.order_id AND
                        (instr(fold(COALESCE(json_extract(i.sale_snapshot,'$.sku'),p.sku)),?) OR
                         instr(fold(COALESCE(json_extract(i.sale_snapshot,'$.name_pl'),p.name_pl)),?) OR
                         instr(fold(COALESCE(json_extract(i.sale_snapshot,'$.name_en'),p.name_en)),?)))"""
            params.extend([product.casefold()] * 3)
        now = datetime.now()

        # --- DATE FILTERING ---
        if date_filter == "last_7":
            query += " AND o.order_date >= ?"
            params.append((now - timedelta(days=7)).strftime('%Y-%m-%d'))
        elif date_filter == "last_30":
            query += " AND o.order_date >= ?"
            params.append((now - timedelta(days=30)).strftime('%Y-%m-%d'))
        elif date_filter == "last_90":
            query += " AND o.order_date >= ?"
            params.append((now - timedelta(days=90)).strftime('%Y-%m-%d'))
        elif date_filter == "last_365":
            query += " AND o.order_date >= ?"
            params.append((now - timedelta(days=365)).strftime('%Y-%m-%d'))
        elif date_filter == "this_week":
            start_of_week = now - timedelta(days=now.weekday())
            query += " AND o.order_date >= ?"
            params.append(start_of_week.strftime('%Y-%m-%d'))
        elif date_filter == "this_month":
            query += " AND o.order_date >= ?"
            params.append(now.replace(day=1).strftime('%Y-%m-%d'))
        elif date_filter == "this_year":
            query += " AND o.order_date >= ?"
            params.append(now.replace(month=1, day=1).strftime('%Y-%m-%d'))
        elif date_filter.startswith("year_"):
            year = date_filter.split("_")[1]
            query += " AND o.order_date LIKE ?"
            params.append(f"{year}-%")

        # --- TEXT SEARCH (ADDRESSES AND NAMES) ---
        if search_term:
            query += """ AND (
                c.first_name LIKE ? OR 
                c.last_name LIKE ? OR 
                o.delivery_city LIKE ? OR
                o.delivery_name LIKE ? OR
                o.delivery_second_name LIKE ? OR
                o.delivery_street LIKE ?
            )"""
            wildcard = f"%{search_term}%"
            params.extend([wildcard] * 6)

        # --- SORTING ---
        if sort_by == "date_desc":
            query += " ORDER BY o.order_date DESC"
        elif sort_by == "date_asc":
            query += " ORDER BY o.order_date ASC"
        elif sort_by == "city_asc":
            query += " ORDER BY o.delivery_city ASC"
        elif sort_by == "city_desc":
            query += " ORDER BY o.delivery_city DESC"
        elif sort_by == "name_asc":
            query += " ORDER BY c.last_name ASC, c.first_name ASC"
        else:
            query += " ORDER BY o.order_id DESC"

        # --- LIMIT ---
        if limit > 0:
            query += " LIMIT ?"
            params.append(limit)

        with sqlite3.connect(self.db_path) as conn:
            # Enable sqlite3.Row to allow UI components to access data by column names
            conn.row_factory = sqlite3.Row
            conn.create_function("fold", 1, lambda s: (s or "").casefold())
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchall()

    def get_order_items(self, order_id):
        """Fetches items associated with a specific order."""
        query = """
            SELECT p.sku, p.name_pl, p.name_en, oi.quantity, oi.unit_price, p.weight, oi.sale_snapshot
            FROM order_items oi
            JOIN products p ON oi.product_id = p.product_id
            WHERE oi.order_id = ?
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(query, (order_id,))
            return cursor.fetchall()

    def add_order(self, customer_id, payment_method_id, created_by, total_amount, delivery_data):
        """
        Creates a new order including the full delivery address.
        delivery_data: dict containing keys 'name', 'second_name', 'street', 'postal_code', 'city'
        """
        query = """
            INSERT INTO orders (
                customer_id, status_code, payment_method_id, created_by, total_amount,
                delivery_name, delivery_second_name, delivery_street, delivery_postal_code, delivery_city
            ) VALUES (?, 'NEW', ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            customer_id, 
            payment_method_id, 
            created_by, 
            total_amount,
            delivery_data.get('name', ''),
            delivery_data.get('second_name', ''),
            delivery_data.get('street', ''),
            delivery_data.get('postal_code', ''),
            delivery_data.get('city', '')
        )

        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            customer = conn.execute("SELECT is_active FROM customers WHERE customer_id = ?", (customer_id,)).fetchone()
            if customer is not None and not customer[0]:
                raise OrderValidationError("inactive_customer")
            cursor = conn.execute(query, params)
            return cursor.lastrowid
