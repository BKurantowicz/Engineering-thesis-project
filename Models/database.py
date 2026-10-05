import sqlite3
import os

class DatabaseManager:
    def __init__(self, db_path="warehouse.db"):
        self.db_path = db_path
        self.initialize_database()

    def get_connection(self):
        """Returns a connection to the SQLite database."""
        return sqlite3.connect(self.db_path)

    def initialize_database(self):
        """Creates tables if they do not exist."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True) if os.path.dirname(self.db_path) else None

        with self.get_connection() as conn:
            cursor = conn.cursor()

            # --- DICTIONARIES (System-wide multilingual lookup tables) ---

            # 1. Order Statuses
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS dict_order_statuses (
                    status_code TEXT PRIMARY KEY,
                    name_pl TEXT NOT NULL,
                    name_en TEXT NOT NULL
                )
            """)

            # 2. Package Types (Dimensions & Base Cost)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS dict_package_types (
                    package_code TEXT PRIMARY KEY,
                    name_pl TEXT NOT NULL,
                    name_en TEXT NOT NULL,
                    max_weight REAL NOT NULL,
                    max_length REAL NOT NULL,
                    max_width REAL NOT NULL,
                    max_height REAL NOT NULL,
                    base_cost REAL NOT NULL
                )
            """)

            # 3. Shipping Methods (Couriers)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS dict_shipping_methods (
                    shipping_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    carrier_name TEXT NOT NULL,
                    service_name_pl TEXT NOT NULL,
                    service_name_en TEXT NOT NULL
                )
            """)

            # --- CORE BUSINESS TABLES ---

            # 4. Users (Warehouse staff & admins)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    first_name TEXT NOT NULL,
                    last_name TEXT NOT NULL,
                    role TEXT NOT NULL -- e.g., 'ADMIN', 'WORKER'
                )
            """)

            # 5. Customers
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS customers (
                    customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    first_name TEXT NOT NULL,
                    last_name TEXT NOT NULL,
                    email TEXT UNIQUE,
                    street TEXT NOT NULL,
                    postal_code TEXT NOT NULL,
                    city TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 6. Products (Integrated bilingual names, descriptions, and physical attributes)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    product_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sku TEXT UNIQUE NOT NULL,
                    name_pl TEXT NOT NULL,
                    name_en TEXT NOT NULL,
                    desc_pl TEXT,
                    desc_en TEXT,
                    price REAL NOT NULL,
                    weight REAL NOT NULL DEFAULT 0.0,
                    length REAL NOT NULL DEFAULT 0.0,
                    width REAL NOT NULL DEFAULT 0.0,
                    height REAL NOT NULL DEFAULT 0.0
                )
            """)

            # 7. Locations (Warehouse Racks / Storage bins)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS locations (
                    location_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    location_code TEXT UNIQUE NOT NULL, -- e.g., A-01-01
                    max_weight REAL NOT NULL,           -- max weight capacity (kg)
                    max_volume REAL NOT NULL            -- max volume capacity (cm3)
                )
            """)

            # 8. Inventory (Stock levels per product and location, composite PK)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS inventory (
                    product_id INTEGER NOT NULL,
                    location_id INTEGER NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (product_id, location_id),
                    FOREIGN KEY(product_id) REFERENCES products(product_id),
                    FOREIGN KEY(location_id) REFERENCES locations(location_id)
                )
            """)

            # 9. Inventory Transactions (Audit trail for stock movements)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS inventory_transactions (
                    transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER NOT NULL,
                    location_id INTEGER NOT NULL,
                    user_id INTEGER,
                    quantity_change INTEGER NOT NULL, -- e.g., -2 (picking), +10 (restock)
                    transaction_type TEXT NOT NULL,   -- e.g., 'ORDER_PICK', 'RESTOCK', 'ADJUSTMENT'
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(product_id) REFERENCES products(product_id),
                    FOREIGN KEY(location_id) REFERENCES locations(location_id),
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                )
            """)

            # 10. Orders (Order headers)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id INTEGER,
                    status_code TEXT DEFAULT 'NEW',
                    created_by INTEGER, -- User who created the order
                    order_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                    total_amount REAL DEFAULT 0.0,
                    FOREIGN KEY(customer_id) REFERENCES customers(customer_id),
                    FOREIGN KEY(status_code) REFERENCES dict_order_statuses(status_code),
                    FOREIGN KEY(created_by) REFERENCES users(user_id)
                )
            """)

            # 11. Order Items (Cart items / order lines)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS order_items (
                    item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER,
                    product_id INTEGER,
                    quantity INTEGER NOT NULL,
                    unit_price REAL NOT NULL,
                    FOREIGN KEY(order_id) REFERENCES orders(order_id),
                    FOREIGN KEY(product_id) REFERENCES products(product_id)
                )
            """)

            # 12. Order Shipments (Shipping and packaging details for an order)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS order_shipments (
                    shipment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL,
                    shipping_id INTEGER NOT NULL,
                    package_code TEXT NOT NULL,
                    tracking_number TEXT,
                    final_shipping_cost REAL NOT NULL,
                    FOREIGN KEY(order_id) REFERENCES orders(order_id),
                    FOREIGN KEY(shipping_id) REFERENCES dict_shipping_methods(shipping_id),
                    FOREIGN KEY(package_code) REFERENCES dict_package_types(package_code)
                )
            """)

            # 13. Invoices
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS invoices (
                    invoice_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER,
                    invoice_number TEXT UNIQUE NOT NULL,
                    company_name TEXT,
                    tax_id TEXT,
                    issue_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(order_id) REFERENCES orders(order_id)
                )
            """)

            # 14. Pick Lists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pick_lists (
                    pick_list_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    status TEXT DEFAULT 'PENDING', -- np. PENDING, PICKING, COMPLETED
                    assigned_user_id INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(assigned_user_id) REFERENCES users(user_id)
                )
            """)

            # 15. Pick List Orders
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pick_list_orders (
                    pick_list_id INTEGER NOT NULL,
                    order_id INTEGER NOT NULL,
                    PRIMARY KEY (pick_list_id, order_id),
                    FOREIGN KEY(pick_list_id) REFERENCES pick_lists(pick_list_id),
                    FOREIGN KEY(order_id) REFERENCES orders(order_id)
                )
            """)

            # --- INITIAL SEED DATA ---

            # Seed default order statuses
            cursor.execute("SELECT COUNT(*) FROM dict_order_statuses")
            if cursor.fetchone()[0] == 0:
                statuses = [
                    ('NEW', 'Nowe', 'New'),
                    ('IN_PROGRESS', 'W realizacji', 'In Progress'),
                    ('PACKED', 'Spakowane', 'Packed'),
                    ('SHIPPED', 'Wysłane', 'Shipped')
                ]
                cursor.executemany("INSERT INTO dict_order_statuses (status_code, name_pl, name_en) VALUES (?, ?, ?)", statuses)

            # Seed default shipping methods
            cursor.execute("SELECT COUNT(*) FROM dict_shipping_methods")
            if cursor.fetchone()[0] == 0:
                carriers = [
                    ('InPost', 'Paczkomat 24/7', 'Parcel Locker 24/7'),
                    ('DPD', 'Kurier Standard', 'Standard Courier'),
                    ('DHL', 'Kurier Express', 'Express Courier')
                ]
                cursor.executemany("INSERT INTO dict_shipping_methods (carrier_name, service_name_pl, service_name_en) VALUES (?, ?, ?)", carriers)

            # Seed default package types
            cursor.execute("SELECT COUNT(*) FROM dict_package_types")
            if cursor.fetchone()[0] == 0:
                packages = [
                    ('INPOST_A', 'Gabaryt A', 'Size A', 25.0, 64.0, 38.0, 8.0, 16.99),
                    ('INPOST_B', 'Gabaryt B', 'Size B', 25.0, 64.0, 38.0, 19.0, 18.99),
                    ('INPOST_C', 'Gabaryt C', 'Size C', 25.0, 64.0, 38.0, 41.0, 20.99),
                    ('CUSTOM_BOX', 'Karton Własny', 'Custom Box', 30.0, 100.0, 100.0, 100.0, 25.00)
                ]
                cursor.executemany("INSERT INTO dict_package_types (package_code, name_pl, name_en, max_weight, max_length, max_width, max_height, base_cost) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", packages)

            conn.commit()

if __name__ == "__main__":
    db = DatabaseManager()
    print(f"Database initialized at: {db.db_path}")