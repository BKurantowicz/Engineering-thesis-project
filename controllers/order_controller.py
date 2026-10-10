import sqlite3
from datetime import datetime, timedelta

class OrderController:
    def __init__(self, db_path="warehouse.db"):
        self.db_path = db_path

    def get_orders(self, limit=50, date_filter=""):
        limit = limit if limit is not None else 50
        date_filter = str(date_filter) if date_filter is not None else ""
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        query = """
            SELECT 
                o.order_id, o.order_date, o.status_code, o.total_amount, 
                c.first_name, c.last_name, 
                pm.name_pl as payment, sh.package_code, sh.tracking_number
            FROM orders o
            LEFT JOIN customers c ON o.customer_id = c.customer_id
            LEFT JOIN dict_payment_methods pm ON o.payment_method_id = pm.id
            LEFT JOIN order_shipments sh ON o.order_id = sh.order_id
            WHERE 1=1
        """
        
        now = datetime.now()
        if date_filter == "last_7":
            query += f" AND o.order_date >= '{(now - timedelta(days=7)).strftime('%Y-%m-%d')}'"
        elif date_filter == "last_30":
            query += f" AND o.order_date >= '{(now - timedelta(days=30)).strftime('%Y-%m-%d')}'"
        elif date_filter == "last_90":
            query += f" AND o.order_date >= '{(now - timedelta(days=90)).strftime('%Y-%m-%d')}'"
        elif date_filter == "last_365":
            query += f" AND o.order_date >= '{(now - timedelta(days=365)).strftime('%Y-%m-%d')}'"
        elif date_filter == "this_week":
            start_of_week = now - timedelta(days=now.weekday())
            query += f" AND o.order_date >= '{start_of_week.strftime('%Y-%m-%d')}'"
        elif date_filter == "this_month":
            query += f" AND o.order_date >= '{now.replace(day=1).strftime('%Y-%m-%d')}'"
        elif date_filter == "this_year":
            query += f" AND o.order_date >= '{now.replace(month=1, day=1).strftime('%Y-%m-%d')}'"
        elif date_filter.startswith("year_"):
            year = date_filter.split("_")[1]
            query += f" AND o.order_date LIKE '{year}-%'"
            
        query += " ORDER BY o.order_date DESC"
        
        if limit > 0:
            query += f" LIMIT {limit}"
            
        cursor.execute(query)
        orders = cursor.fetchall()
        conn.close()
        return orders

    def get_order_items(self, order_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        query = """
            SELECT p.sku, p.name_pl, oi.quantity, oi.unit_price, p.weight
            FROM order_items oi
            JOIN products p ON oi.product_id = p.product_id
            WHERE oi.order_id = ?
        """
        cursor.execute(query, (order_id,))
        items = cursor.fetchall()
        conn.close()
        return items