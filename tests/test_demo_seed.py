"""Explicit, repeatable demo generation never changes an unapproved target."""

from contextlib import closing
import gc
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


if __name__ == "__main__":
    unittest.main()
