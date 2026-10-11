import sqlite3
from datetime import datetime, timedelta

class DashboardController:
    def __init__(self, db_path):
        self.db_path = db_path

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_order_status_counts(self):
        """Fetches all active backlog, and SHIPPED orders strictly from the latest active date."""
        counts = {"NEW": 0, "IN_PROGRESS": 0, "PACKED": 0, "SHIPPED": 0} 
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # 1. Fetch all pending/active orders
                cursor.execute("""
                    SELECT status_code, COUNT(order_id) as count 
                    FROM orders 
                    WHERE status_code != 'SHIPPED'
                    GROUP BY status_code
                """)
                for row in cursor.fetchall():
                    status = row['status_code'].upper() if row['status_code'] else ""
                    if status in counts:
                        counts[status] = row['count']
                
                # 2. Fetch SHIPPED orders ONLY from the latest date that has any shipped orders
                cursor.execute("""
                    SELECT COUNT(order_id) as count 
                    FROM orders 
                    WHERE status_code = 'SHIPPED' 
                    AND DATE(order_date) = (
                        SELECT MAX(DATE(order_date)) 
                        FROM orders 
                        WHERE status_code = 'SHIPPED'
                    )
                """)
                shipped_row = cursor.fetchone()
                if shipped_row and shipped_row['count']:
                    counts['SHIPPED'] = shipped_row['count']
                    
        except Exception as e:
            print(f"Error fetching order statuses from database: {e}")
            
        return counts

    def get_warehouse_capacity(self):
        MAX_CAPACITY = 10000 
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT SUM(quantity) as total_items FROM inventory")
                result = cursor.fetchone()
                total_items = result['total_items'] if result['total_items'] else 0
                
                taken_racks_pct = (total_items / MAX_CAPACITY) * 100
                in_picking_pct = taken_racks_pct * 0.05 
                free_pct = 100.0 - taken_racks_pct - in_picking_pct
                
                return {
                    "free_space": max(0, free_pct),
                    "taken_on_racks": max(0, taken_racks_pct),
                    "in_picking": max(0, in_picking_pct)
                }
        except Exception as e:
            print(f"Error calculating warehouse capacity: {e}")
            return {"free_space": 100, "taken_on_racks": 0, "in_picking": 0}

    def get_order_trend(self, filter_type="7_days"):
        """Fetches dynamic order inflow trend based on UI combobox selection."""
        trend_data = {}
        today = datetime.now()

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                if filter_type == "7_days" or filter_type == "this_month":
                    days = 7 if filter_type == "7_days" else 30
                    # Pre-fill continuous dates (e.g., last 7 or 30 days) to prevent chart gaps
                    for i in range(days - 1, -1, -1):
                        date_str = (today - timedelta(days=i)).strftime('%Y-%m-%d')
                        trend_data[date_str] = 0
                        
                    cursor.execute(f"""
                        SELECT DATE(order_date) as dt, COUNT(order_id) as count
                        FROM orders
                        WHERE order_date >= date('now', '-{days} days')
                        GROUP BY DATE(order_date)
                        ORDER BY dt ASC
                    """)
                    for row in cursor.fetchall():
                        if row['dt'] in trend_data:
                            trend_data[row['dt']] = row['count']
                            
                elif filter_type == "this_year":
                    # Pre-fill last 12 calendar months (YYYY-MM)
                    for i in range(11, -1, -1):
                        m = today.month - i
                        y = today.year
                        while m <= 0:
                            m += 12
                            y -= 1
                        month_str = f"{y}-{m:02d}"
                        trend_data[month_str] = 0
                        
                    cursor.execute("""
                        SELECT strftime('%Y-%m', order_date) as dt, COUNT(order_id) as count
                        FROM orders
                        WHERE order_date >= date('now', '-1 year')
                        GROUP BY dt
                        ORDER BY dt ASC
                    """)
                    for row in cursor.fetchall():
                        if row['dt'] in trend_data:
                            trend_data[row['dt']] = row['count']
                            
        except Exception as e:
            print(f"Error fetching order trend data: {e}")
            
        return trend_data