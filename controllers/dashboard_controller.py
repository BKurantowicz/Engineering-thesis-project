import sqlite3
from datetime import datetime, timedelta

class DashboardController:
    def __init__(self, db_path):
        self.db_path = db_path

    def _get_connection(self):
        # Open database connection with row factory enabled for column name mapping
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_order_status_counts(self):
        """Fetch order counts grouped by their current status from the database"""
        query = """
            SELECT status, COUNT(id) as count 
            FROM orders 
            GROUP BY status
        """
        # Default fallback values for each status
        counts = {"New": 0, "In Progress": 0, "Partially packed": 0, "Packed": 0}
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                rows = cursor.fetchall()
                
                # Override defaults with actual data from database
                for row in rows:
                    status = row['status']
                    if status in counts:
                        counts[status] = row['count']
        except Exception as e:
            print(f"Error fetching order statuses from database: {e}")
            
        return counts

    def get_warehouse_capacity(self):
        """Calculate percentage-based warehouse capacity utilization from inventory table"""
        # Maximum warehouse capacity (to be replaced later with rack calculations)
        MAX_CAPACITY = 10000 
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # Sum up all physical items currently stored in the warehouse
                cursor.execute("SELECT SUM(quantity) as total_items FROM inventory")
                result = cursor.fetchone()
                total_items = result['total_items'] if result['total_items'] else 0
                
                # Compute percentages for the pie chart
                taken_racks_pct = (total_items / MAX_CAPACITY) * 100
                in_picking_pct = taken_racks_pct * 0.05 # Simulation: 5% of stock is currently being picked
                free_pct = 100.0 - taken_racks_pct - in_picking_pct
                
                return {
                    "free_space": max(0, free_pct),
                    "taken_on_racks": max(0, taken_racks_pct),
                    "in_picking": max(0, in_picking_pct)
                }
        except Exception as e:
            print(f"Error calculating warehouse capacity: {e}")
            return {"free_space": 100, "taken_on_racks": 0, "in_picking": 0}

    def get_order_trend(self, days=7):
        """Fetch order inflow quantities from the last X days, grouped by date"""
        query = """
            SELECT DATE(created_at) as order_date, COUNT(id) as count
            FROM orders
            WHERE created_at >= date('now', ?)
            GROUP BY DATE(created_at)
            ORDER BY DATE(created_at) ASC
        """
        trend_data = {}
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # Safe parameterized query against SQL injection with dynamic date shift
                cursor.execute(query, (f'-{days} days',))
                rows = cursor.fetchall()
                
                for row in rows:
                    trend_data[row['order_date']] = row['count']
        except Exception as e:
            print(f"Error fetching order trend data: {e}")
            
        return trend_data