"""Search contact records and preserve selected identities through maintenance."""

import unittest
from unittest.mock import patch

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

import test_customer_lifecycle as lifecycle


class CustomerSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        lifecycle.CustomerLifecycleTests.setUpClass()

    def setUp(self):
        self.case = lifecycle.CustomerLifecycleTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.controller = self.case.controller

    def test_search_matches_each_contract_field_with_unicode_casefold_and_literal_punctuation(self):
        customer = dict(self.controller.get_customer(self.case.first))
        customer.update(first_name="Łukasz", last_name="Żółć", email="Lukasz@Example.test", city="ŁÓDŹ_100%")
        self.controller.save_customer(customer, self.case.first)
        for query in ("ŁUKASZ", "żółć", "EXAMPLE.TEST", "łódź", "_100%", "  łUkAsZ  "):
            with self.subTest(query=query):
                self.assertEqual([row["customer_id"] for row in self.controller.get_customers(query)], [self.case.first])
        self.assertEqual(self.controller.get_customers("%_%"), [])
        self.assertEqual(self.controller.get_customers("' OR 1=1 --"), [])
        self.assertEqual(len(self.controller.get_customers("  ")), 2)

    def test_inactive_customers_remain_searchable_and_empty_states_are_translated(self):
        self.controller.set_active(self.case.first, False)
        before = self.case.dump()
        for language in ("en", "pl"):
            view = self.case.open_view(language)
            view.search_input.setText("ANNA")
            self.assertEqual(view.table.rowCount(), 1)
            self.assertEqual(view.table.item(0, view.COLUMNS.index("is_active")).text(), view.t("cust_inactive"))
            view.table.selectRow(0)
            self.assertEqual(view.selected_customer_id(), self.case.first)
            view.search_input.setText("No match")
            self.assertEqual(view.table.rowCount(), 0)
            self.assertEqual(view.message.text(), view.t("cust_no_matches"))
            self.assertFalse(view.active_button.isEnabled())
            self.assertFalse(view.delete_button.isEnabled())
            view.search_input.clear()
            self.assertEqual(view.table.rowCount(), 2)
        self.assertEqual(self.case.dump(), before)
        self.controller.delete_customer(self.case.first)
        self.controller.delete_customer(self.case.second)
        view.search_input.clear()
        view.load_customers()
        self.assertEqual(view.message.text(), view.t("cust_empty"))

    def test_filtered_lifecycle_and_delete_target_the_matching_customer_only(self):
        view = self.case.open_view("en")
        view.search_input.setText("ANNA")
        view.table.selectRow(0)
        view.active_button.click()
        self.assertEqual(view.search_input.text(), "ANNA")
        self.assertEqual(self.controller.get_customer(self.case.first)["is_active"], 0)
        self.assertEqual(self.controller.get_customer(self.case.second)["is_active"], 1)
        with patch.object(view, "confirm_delete", return_value=True):
            view.delete_button.click()
        self.assertEqual(view.table.rowCount(), 0)
        self.assertEqual(view.message.text(), view.t("cust_no_matches"))
        view.search_input.clear()
        self.assertEqual(view.table.rowCount(), 1)
        view.table.selectRow(0)
        self.assertEqual(view.selected_customer_id(), self.case.second)

    def test_filtered_edit_keeps_query_and_drops_a_record_that_no_longer_matches(self):
        view = self.case.open_view("en")
        view.search_input.setText("ANNA")
        view.table.selectRow(0)
        def save_editor():
            dialog = QApplication.activeModalWidget()
            self.assertEqual(dialog.customer_id, self.case.first)
            dialog.fields["first_name"].setText("Caroline")
            dialog.save()
        QTimer.singleShot(0, save_editor)
        view.edit_button.click()
        self.assertEqual(view.search_input.text(), "ANNA")
        self.assertEqual(view.table.rowCount(), 0)
        self.assertEqual(self.controller.get_customer(self.case.first)["first_name"], "Caroline")
        self.assertEqual(self.controller.get_customer(self.case.second)["first_name"], "Betty")
        view.search_input.clear()
        self.assertEqual(view.table.rowCount(), 2)


if __name__ == "__main__":
    unittest.main()
