"""Explicit, repeatable demo generation never changes an unapproved target."""

from contextlib import closing
import gc
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from controllers.capacity_controller import CapacityController
from controllers.inventory_controller import InventoryController, connect
from controllers.pick_list_controller import PickListController
from seed_demo import seed_demo


class DemoSeedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(gc.collect)
        self.path = Path(self.temp.name) / "demo.db"

    def counts(self):
        with closing(sqlite3.connect(self.path)) as connection:
            return {table: connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] for table in ("products", "customers", "orders", "pick_lists", "pick_allocations", "shortage_events")}

    def test_dataset_has_consistent_open_partial_closed_and_cancelled_examples(self):
        ids = seed_demo(self.path)
        picking = PickListController(str(self.path))
        self.assertEqual(picking.get_list(ids["open"])["status"], "PENDING")
        partial = picking.get_list(ids["partial"])
        self.assertEqual(partial["status"], "IN_PROGRESS")
        self.assertTrue(any(line["picked_quantity"] > 0 and line["reserved_quantity"] > 0 for line in partial["lines"]))
        self.assertEqual(picking.get_list(ids["closed"])["status"], "CLOSED")
        self.assertTrue(all(line["order_status"] == "CANCELLED" for line in picking.get_list(ids["shortage"])["lines"]))
        self.assertEqual(len(picking.get_missing_stock()), 1)
        self.assertEqual(picking.get_missing_stock()[0]["missing_quantity"], 1)
        capacity = CapacityController(str(self.path)).get_capacity()
        self.assertEqual(len(capacity["racks"]), 3)
        for rack in capacity["racks"]:
            for metric in ("weight", "volume"):
                self.assertIsNotNone(rack[metric]["percentage"])
                self.assertLessEqual(rack[metric]["percentage"], 100)
        with closing(connect(str(self.path))) as connection:
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            for row in InventoryController(str(self.path)).stock_snapshot(connection):
                self.assertLessEqual(row["reserved"], row["quantity"])
                self.assertNotEqual(row["location_code"], "braki")
        with closing(connect(str(self.path))) as db:
            for order in db.execute("SELECT * FROM orders"):
                delivery = json.loads(order["sales_snapshot"])["delivery_line"]
                self.assertEqual((delivery["vat"], delivery["net_cents"], delivery["gross_cents"]), ("8", 1000, 1080))
                prices = [json.loads(r[0]) for r in db.execute(
                    "SELECT sale_snapshot FROM order_items WHERE order_id=?", (order["order_id"],))]
                self.assertTrue(prices)
                self.assertTrue(all(line["vat"] == "23" for line in prices))
                self.assertEqual(order["net_cents"], sum(line["net_cents"] for line in prices) + delivery["net_cents"])
                self.assertEqual(round(order["total_amount"]*100), sum(line["gross_cents"] for line in prices) + delivery["gross_cents"])
        counts = self.counts()
        self.assertEqual(seed_demo(self.path, replace_mock=True), ids)
        self.assertEqual(self.counts(), counts)
        self.assertEqual(list(Path(self.temp.name).glob(".thesis-demo-*")), [])

    def test_existing_target_requires_explicit_replacement_and_failed_build_preserves_it(self):
        seed_demo(self.path)
        before = self.path.read_bytes()
        with self.assertRaises(FileExistsError):
            seed_demo(self.path)
        self.assertEqual(self.path.read_bytes(), before)
        with patch("seed_demo.build_demo", side_effect=RuntimeError("failed fixture")):
            with self.assertRaises(RuntimeError):
                seed_demo(self.path, replace_mock=True)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(Path(self.temp.name).glob(".thesis-demo-*")), [])

    def test_large_profile_preserves_fulfillment_and_routes_only_to_test_aliases(self):
        from controllers.customer_controller import CustomerController
        from controllers.dispatch_controller import DispatchController
        from controllers.product_controller import ProductController
        with patch("smtplib.SMTP") as smtp, patch("smtplib.SMTP_SSL") as secure_smtp:
            ids = seed_demo(self.path, profile="large", test_email="demo.owner@gmail.com")
        smtp.assert_not_called()
        secure_smtp.assert_not_called()
        counts = self.counts()
        self.assertEqual([counts[t] for t in ("products", "customers", "orders")], [100, 50, 300])
        self.assertEqual(CustomerController(str(self.path)).get_email_conflicts(), [])
        with closing(connect(str(self.path))) as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual({r[0] for r in db.execute("SELECT email FROM customers")},
                             {f"demo.owner+demo{n:03d}@gmail.com" for n in range(1, 51)})
            self.assertEqual(db.execute("SELECT COUNT(DISTINCT ean) FROM products").fetchone()[0], 100)
            for product in db.execute("SELECT * FROM products"):
                ProductController.validate(dict(product))
            for order in db.execute("SELECT * FROM orders"):
                snapshot = json.loads(order["sales_snapshot"])
                self.assertRegex(snapshot["recipient"]["email"], r"^demo\.owner\+demo\d{3}@gmail\.com$")
                lines = [json.loads(r[0]) for r in db.execute("SELECT sale_snapshot FROM order_items WHERE order_id=?", (order["order_id"],))]
                lines.append(snapshot["delivery_line"])
                self.assertEqual(order["net_cents"], sum(line["net_cents"] for line in lines))
                self.assertEqual(round(order["total_amount"]*100), sum(line["gross_cents"] for line in lines))
                invoices = db.execute("SELECT COUNT(*) FROM invoices WHERE order_id=?", (order["order_id"],)).fetchone()[0]
                self.assertEqual(invoices, int(order["status_code"] == "SHIPPED"))
            partial = ids["examples"]["partial_dispatch"]
            self.assertEqual(db.execute("SELECT COUNT(*) FROM order_shipments WHERE order_id=? AND dispatched_at IS NOT NULL", (partial,)).fetchone()[0], 1)
            self.assertEqual({r[0] for r in db.execute("SELECT state FROM dispatch_mail")}, {"pending"})
            for row in InventoryController(str(self.path)).stock_snapshot(db):
                self.assertLessEqual(row["reserved"], row["quantity"])
        self.assertIn(ids["examples"]["picked"], DispatchController(str(self.path)).work_orders())
        capacity = CapacityController(str(self.path)).get_capacity()
        self.assertEqual(len(capacity["racks"]), 23)
        for rack in capacity["racks"]:
            for metric in ("weight", "volume"):
                self.assertLessEqual(rack[metric]["percentage"], 100)

    def test_invalid_large_inbox_preserves_existing_mock_database(self):
        seed_demo(self.path)
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            seed_demo(self.path, replace_mock=True, profile="large", test_email="not-an-address")
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
