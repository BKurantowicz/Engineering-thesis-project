"""Reservation, picking, and cross-list shortage transaction regressions."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import unittest

from controllers.inventory_controller import WarehouseError
from controllers.pick_list_controller import PickListController
from controllers.shortage_controller import ShortageController
import test_products_inventory as products


class PickListTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        products.ProductInventoryTests.setUpClass()

    def setUp(self):
        self.case = products.ProductInventoryTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.controller = PickListController(self.case.db_path)
        self.shortages = ShortageController(self.case.db_path)
        self.product_id = self.case.product_id

    def order(self, demands, date="2026-01-01 10:00:00"):
        self.case.sql("INSERT INTO orders (order_date, status_code) VALUES (?, 'NEW')", (date,))
        order_id = self.case.sql("SELECT MAX(order_id) FROM orders")[0][0]
        for product_id, quantity in demands:
            self.case.sql("INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (?, ?, ?, 12.30)", (order_id, product_id, quantity))
        return order_id

    def allocate(self, order_ids, location_id=1):
        lines = []
        for order_id in order_ids:
            for item_id, quantity in self.case.sql("SELECT item_id, quantity FROM order_items WHERE order_id = ?", (order_id,)):
                lines.append(dict(order_item_id=item_id, location_id=location_id, quantity=quantity))
        return self.controller.create_list(order_ids, lines)

    def test_generation_persists_manual_multi_rack_sources_and_reserves_without_physical_deduction(self):
        self.case.inventory.add_stock(self.product_id, 1, 3)
        self.case.inventory.add_stock(self.product_id, 2, 4)
        order_id = self.order([(self.product_id, 5)])
        options = self.controller.allocation_options([order_id])
        self.assertEqual([source["available"] for source in options[0]["sources"]], [3, 4])
        item_id = options[0]["item_id"]
        list_id = self.controller.create_list([order_id], [dict(order_item_id=item_id, location_id=1, quantity=3), dict(order_item_id=item_id, location_id=2, quantity=2)])
        self.assertEqual(self.case.sql("SELECT SUM(quantity) FROM inventory"), [(7,)])
        self.assertEqual(self.case.controller.get_products()[0]["available"], 2)
        before = self.case.dump()
        reopened = PickListController(self.case.db_path).get_list(list_id)
        self.assertEqual([(line["order_id"], line["location_code"], line["quantity"]) for line in reopened["lines"]], [(order_id, "A", 3), (order_id, "B", 2)])
        self.assertEqual(self.case.dump(), before)
        self.case.assert_rejected_unchanged("order_not_eligible", lambda: self.allocate([order_id]))

    def test_generation_rejects_empty_incomplete_virtual_and_insufficient_allocations_atomically(self):
        self.case.inventory.add_stock(self.product_id, 1, 3)
        order_id = self.order([(self.product_id, 5)])
        item_id = self.case.sql("SELECT item_id FROM order_items")[0][0]
        self.case.assert_rejected_unchanged("select_orders", lambda: self.controller.create_list([], []))
        self.case.assert_rejected_unchanged("allocation_mismatch", lambda: self.controller.create_list([order_id], [dict(order_item_id=item_id, location_id=1, quantity=2)]))
        self.case.assert_rejected_unchanged("insufficient_available", lambda: self.allocate([order_id]))
        self.case.sql("INSERT INTO inventory VALUES (?, 3, 20)", (self.product_id,))
        self.case.assert_rejected_unchanged("insufficient_available", lambda: self.allocate([order_id], 3))
        self.assertEqual(self.case.sql("SELECT COUNT(*) FROM pick_lists"), [(0,)])

    def test_concurrent_lists_cannot_reserve_the_same_units(self):
        self.case.inventory.add_stock(self.product_id, 1, 5)
        orders = [self.order([(self.product_id, 5)]) for _ in range(2)]
        barrier = Barrier(2)
        def generate(order_id):
            barrier.wait()
            try:
                return self.allocate([order_id])
            except WarehouseError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(generate, orders))
        self.assertEqual(results.count("insufficient_available"), 1)
        self.assertEqual(self.case.sql("SELECT SUM(reserved_quantity) FROM pick_allocations"), [(5,)])

    def test_start_cumulative_confirmation_close_and_exclusion_of_fully_picked_orders(self):
        self.case.inventory.add_stock(self.product_id, 1, 5)
        order_id = self.order([(self.product_id, 5)])
        list_id = self.allocate([order_id])
        line_id = self.controller.get_list(list_id)["lines"][0]["allocation_id"]
        self.case.assert_rejected_unchanged("list_not_started", lambda: self.controller.confirm_pick(line_id, 1))
        self.controller.start_list(list_id)
        self.assertEqual(self.case.sql("SELECT status_code FROM orders"), [("IN_PROGRESS",)])
        self.controller.confirm_pick(line_id, 2)
        self.controller.confirm_pick(line_id, 2)
        self.assertEqual(self.case.sql("SELECT quantity FROM inventory WHERE location_id = 1"), [(3,)])
        self.assertEqual(PickListController(self.case.db_path).get_list(list_id)["lines"][0]["picked_quantity"], 2)
        self.case.assert_rejected_unchanged("invalid_picked_total", lambda: self.controller.confirm_pick(line_id, 6))
        self.case.assert_rejected_unchanged("list_incomplete", lambda: self.controller.close_list(list_id))
        self.case.controller.set_active(self.product_id, False)
        self.controller.confirm_pick(line_id, 5)
        self.controller.close_list(list_id)
        self.controller.close_list(list_id)
        self.controller.confirm_pick(line_id, 5)
        self.assertEqual(self.case.sql("SELECT status_code FROM orders"), [("IN_PROGRESS",)])
        self.assertEqual(self.case.sql("SELECT quantity FROM inventory WHERE location_id = 1"), [(0,)])
        self.assertEqual(self.controller.get_eligible_orders(), [])
        self.case.assert_rejected_unchanged("order_not_eligible", lambda: self.allocate([order_id]))

    def test_shortage_uses_chronological_complete_orders_skipping_unfillable_demands(self):
        self.case.inventory.add_stock(self.product_id, 1, 11)
        orders = [self.order([(self.product_id, quantity)], f"2026-01-0{index} 10:00:00") for index, quantity in enumerate((5, 4, 2), 1)]
        list_id = self.allocate(orders)
        result = self.shortages.reconcile(list_id, self.product_id, 1, 7, "short-7")
        self.assertEqual(result["fulfilled"], [orders[0], orders[2]])
        self.assertEqual(result["cancelled"], [orders[1]])
        self.assertEqual(result["missing_quantity"], 4)
        self.assertEqual(self.case.sql("SELECT SUM(reserved_quantity) FROM pick_allocations"), [(7,)])
        self.assertEqual(self.case.sql("SELECT quantity FROM inventory WHERE location_id = 3"), [(4,)])
        before = self.case.dump()
        self.assertEqual(self.shortages.reconcile(list_id, self.product_id, 1, 7, "short-7"), result)
        self.assertEqual(self.case.dump(), before)
        self.case.assert_rejected_unchanged("operation_conflict", lambda: self.shortages.reconcile(list_id, self.product_id, 1, 6, "short-7"))
        self.controller.start_list(list_id)
        for line in self.controller.get_list(list_id)["lines"]:
            if line["reserved_quantity"]:
                self.controller.confirm_pick(line["allocation_id"], line["quantity"])
        self.controller.close_list(list_id)
        self.assertEqual(len(self.controller.get_missing_stock()), 1)

    def test_shortage_reconciles_affected_lists_together_and_preserves_unaffected_reservations(self):
        self.case.inventory.add_stock(self.product_id, 1, 8)
        self.case.inventory.add_stock(self.product_id, 2, 2)
        older = self.order([(self.product_id, 5)], "2026-01-01 10:00:00")
        newer = self.order([(self.product_id, 3)], "2026-01-02 10:00:00")
        unaffected = self.order([(self.product_id, 2)], "2026-01-03 10:00:00")
        first, second, third = self.allocate([older]), self.allocate([newer]), self.allocate([unaffected], 2)
        before_third = self.controller.get_list(third)
        result = self.shortages.reconcile(second, self.product_id, 1, 3, "cross-list")
        self.assertEqual(result["affected_lists"], [first, second])
        self.assertEqual(result["cancelled"], [older])
        self.assertEqual(result["fulfilled"], [newer])
        self.assertEqual(self.controller.get_list(third), before_third)
        self.assertEqual(self.case.controller.get_products()[0]["available"], 0)

    def prepare_picked_return(self):
        other = self.case.controller.save_product(dict(products.PRODUCT, sku="MISSING", weight="1", length="10", width="10", height="10"))
        self.case.inventory.add_stock(self.product_id, 1, 3)
        self.case.inventory.add_stock(other, 1, 1)
        order_id = self.order([(self.product_id, 3), (other, 1)])
        list_id = self.allocate([order_id])
        self.controller.start_list(list_id)
        first_line = next(line for line in self.controller.get_list(list_id)["lines"] if line["product_id"] == self.product_id)
        self.controller.confirm_pick(first_line["allocation_id"], 3)
        self.case.sql("UPDATE locations SET max_volume = 0.02 WHERE location_id = 1")
        self.case.sql("UPDATE locations SET max_volume = 0.04 WHERE location_id = 2")
        return other, order_id, list_id

    def test_cancelled_order_returns_existing_picked_goods_across_racks_and_records_only_missing(self):
        other, order_id, list_id = self.prepare_picked_return()
        result = self.shortages.reconcile(list_id, other, 1, 0, "return-split")
        self.assertEqual(result["cancelled"], [order_id])
        self.assertEqual(result["fulfilled"], [])
        self.assertEqual([(entry["location_id"], entry["quantity"]) for entry in result["returns"]], [(1, 1), (2, 2)])
        self.assertEqual(self.case.sql("SELECT product_id, quantity FROM inventory WHERE location_id = 3"), [(other, 1)])
        self.assertEqual(self.case.sql("SELECT SUM(quantity) FROM inventory WHERE product_id = ?", (self.product_id,)), [(3,)])
        self.assertEqual(self.case.sql("SELECT SUM(reserved_quantity), SUM(returned_quantity) FROM pick_allocations"), [(0, 3)])
        self.assertEqual(self.case.sql("SELECT status_code, cancellation_reason FROM orders"), [("CANCELLED", "SHORTAGE:return-split")])
        self.controller.close_list(list_id)
        before = self.case.dump()
        self.shortages.reconcile(list_id, other, 1, 0, "return-split")
        self.assertEqual(self.case.dump(), before)

    def test_no_capacity_for_a_physical_return_rolls_back_entire_reconciliation(self):
        other, _, list_id = self.prepare_picked_return()
        self.case.sql("UPDATE locations SET max_volume = 0.02 WHERE location_id = 2")
        self.case.assert_rejected_unchanged("return_capacity", lambda: self.shortages.reconcile(list_id, other, 1, 0, "no-room"))
        self.assertEqual(self.case.sql("SELECT COUNT(*) FROM shortage_events"), [(0,)])

    def test_count_rejects_intervening_stock_changes_and_zero_stock_cancels_all_orders(self):
        self.case.inventory.add_stock(self.product_id, 1, 2)
        orders = [self.order([(self.product_id, 1)]) for _ in range(2)]
        list_id = self.allocate(orders)
        self.case.inventory.add_stock(self.product_id, 1, 1)
        self.case.assert_rejected_unchanged("stock_changed", lambda: self.shortages.reconcile(list_id, self.product_id, 1, 0, "count", recorded_quantity=2))
        result = self.shortages.reconcile(list_id, self.product_id, 1, 0, "count", recorded_quantity=3)
        self.assertEqual(result["fulfilled"], [])
        self.assertEqual(result["cancelled"], orders)
        self.assertEqual(self.case.sql("SELECT SUM(reserved_quantity) FROM pick_allocations"), [(0,)])


if __name__ == "__main__":
    unittest.main()
