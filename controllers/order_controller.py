import sqlite3

class OrderController:
    """Kontroler obsługujący logikę bazy danych dla modułu zamówień."""
    def __init__(self, db_path="warehouse.db"):
        self.db_path = db_path

    def get_orders(self, limit=50):
        """Pobiera listę głównych zamówień wraz z danymi klienta."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        query = """
            SELECT 
                o.order_id, o.order_date, o.status_code, o.total_amount, 
                c.first_name, c.last_name
            FROM orders o
            LEFT JOIN customers c ON o.customer_id = c.customer_id
            ORDER BY o.order_date DESC
        """
        # limit 0 oznacza "Wszystkie"
        if limit > 0:
            query += f" LIMIT {limit}"
            
        cursor.execute(query)
        orders = cursor.fetchall()
        conn.close()
        return orders

    def get_order_items(self, order_id):
        """Pobiera zawartość koszyka (produkty) dla konkretnego zamówienia."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        query = """
            SELECT 
                p.sku, p.name_pl, oi.quantity, oi.unit_price, p.weight
            FROM order_items oi
            JOIN products p ON oi.product_id = p.product_id
            WHERE oi.order_id = ?
        """
        cursor.execute(query, (order_id,))
        items = cursor.fetchall()
        conn.close()
        return items