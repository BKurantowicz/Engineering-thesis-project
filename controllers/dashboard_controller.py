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
        """Calculate percentage-based warehouse capacity utilization from inventory table"""
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
        """Fetches dynamic order inflow trend for both current and previous periods."""
        trend_data = {'dates': [], 'current': [], 'previous': []}
        today = datetime.now()

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                if filter_type == "7_days" or filter_type == "this_month":
                    days = 7 if filter_type == "7_days" else 30
                    
                    # Generate EXACT dates to avoid mismatch
                    for i in range(days - 1, -1, -1):
                        curr_dt = today - timedelta(days=i)
                        
                        trend_data['dates'].append(curr_dt.strftime('%Y-%m-%d'))
                        trend_data['current'].append(0)
                        trend_data['previous'].append(0)
                        
                    # 1. Query current period
                    cursor.execute(f"""
                        SELECT DATE(order_date) as dt, COUNT(order_id) as count
                        FROM orders
                        WHERE DATE(order_date) >= ? 
                        GROUP BY DATE(order_date)
                    """, (trend_data['dates'][0],))
                    
                    for row in cursor.fetchall():
                        if row['dt'] in trend_data['dates']:
                            idx = trend_data['dates'].index(row['dt'])
                            trend_data['current'][idx] = row['count']
                            
                    # 2. Query previous period
                    prev_start = (today - timedelta(days=days*2 - 1)).strftime('%Y-%m-%d')
                    prev_end = (today - timedelta(days=days)).strftime('%Y-%m-%d')
                    
                    cursor.execute(f"""
                        SELECT DATE(order_date) as dt, COUNT(order_id) as count
                        FROM orders
                        WHERE DATE(order_date) >= ? AND DATE(order_date) <= ?
                        GROUP BY DATE(order_date)
                    """, (prev_start, prev_end))
                    
                    for row in cursor.fetchall():
                        # Shift the old date forward to match the current X-axis index
                        row_dt = datetime.strptime(row['dt'], '%Y-%m-%d')
                        mapped_dt = (row_dt + timedelta(days=days)).strftime('%Y-%m-%d')
                        
                        if mapped_dt in trend_data['dates']:
                            idx = trend_data['dates'].index(mapped_dt)
                            trend_data['previous'][idx] = row['count']

                elif filter_type == "this_year":
                    for i in range(11, -1, -1):
                        curr_m = today.month - i
                        curr_y = today.year
                        while curr_m <= 0:
                            curr_m += 12
                            curr_y -= 1
                        trend_data['dates'].append(f"{curr_y}-{curr_m:02d}")
                        trend_data['current'].append(0)
                        trend_data['previous'].append(0)
                        
                    # 1. Query current year
                    cursor.execute("""
                        SELECT strftime('%Y-%m', order_date) as dt, COUNT(order_id) as count
                        FROM orders
                        WHERE order_date >= date('now', '-1 year')
                        GROUP BY dt
                    """)
                    for row in cursor.fetchall():
                        if row['dt'] in trend_data['dates']:
                            idx = trend_data['dates'].index(row['dt'])
                            trend_data['current'][idx] = row['count']
                            
                    # 2. Query previous year
                    cursor.execute("""
                        SELECT strftime('%Y-%m', order_date) as dt, COUNT(order_id) as count
                        FROM orders
                        WHERE order_date >= date('now', '-2 years') 
                        AND order_date < date('now', '-1 year')
                        GROUP BY dt
                    """)
                    for row in cursor.fetchall():
                        # Shift the old year forward to match the current X-axis index
                        y, m = map(int, row['dt'].split('-'))
                        mapped_dt = f"{y + 1}-{m:02d}"
                        
                        if mapped_dt in trend_data['dates']:
                            idx = trend_data['dates'].index(mapped_dt)
                            trend_data['previous'][idx] = row['count']
                            
        except Exception as e:
            print(f"Error fetching order trend data: {e}")
            
        return trend_data