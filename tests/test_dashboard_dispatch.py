"""Today's completed dispatches are independent of the order's creation date."""
from contextlib import closing
from datetime import datetime
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from controllers.dashboard_controller import DashboardController


class DashboardDispatchTests(unittest.TestCase):
    def test_final_parcel_date_counts_each_completed_order_once(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "dashboard.db")
            with closing(sqlite3.connect(path)) as db, db:
                db.executescript("""
                    CREATE TABLE orders(order_id INTEGER PRIMARY KEY, status_code TEXT, order_date TEXT);
                    CREATE TABLE order_shipments(order_id INTEGER, package_id INTEGER, dispatched_at TEXT);
                """)
                db.executemany("INSERT INTO orders VALUES(?,?,?)", [
                    (1, "SHIPPED", "2026-10-01"), (2, "SHIPPED", "2026-11-05"),
                    (3, "PACKED", "2026-10-01"), (4, "SHIPPED", "2026-11-05"),
                    (5, "SHIPPED", "2026-10-01"), (6, "NEW", "2026-11-05"),
                    (7, "SHIPPED", "2026-11-05"), (8, "SHIPPED", "2026-11-05"),
                    (9, "SHIPPED", "2026-11-05"),
                ])
                db.executemany("INSERT INTO order_shipments VALUES(?,?,?)", [
                    (1, 1, "2026-11-04 18:00:00"), (1, 2, "2026-11-05 00:05:00"),
                    (2, 3, "2026-11-04 23:59:00"),
                    (3, 4, "2026-11-05 00:05:00"), (3, 5, None),
                    (4, None, "2026-11-05 00:05:00"),
                    (5, 6, "2026-11-05 00:02:00"), (5, 7, "2026-11-05 00:05:00"),
                    (8, 8, None),
                    (9, 9, "2026-11-05 00:05:00"), (9, 10, None),
                ])
            with patch("controllers.dashboard_controller.datetime") as clock:
                clock.now.return_value = datetime(2026, 11, 5, 0, 10)
                counts = DashboardController(path).get_order_status_counts()
            self.assertEqual(counts, {"NEW": 1, "IN_PROGRESS": 0, "PACKED": 1, "SHIPPED": 2})


if __name__ == "__main__":
    unittest.main()
