"""Reproduce R-01..03 using isolated warehouses and real controller/UI paths."""
from contextlib import closing
import sqlite3
import unittest
from unittest.mock import patch

import test_qa_thesis as qa
from controllers import auth_controller
from controllers.auth_controller import AuthError
from controllers.dispatch_controller import DispatchController
from controllers.dispatch_mail import DispatchMail
from views.orders.dispatch_view import DispatchDialog, MailWorker
from utils.translations import translator


class ReviewRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        qa.ThesisOperationsTests.setUpClass()
        cls.app = qa.ThesisOperationsTests.app

    def setUp(self):
        self.case = qa.ThesisOperationsTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.t = translator('en', str(qa.ROOT / 'utils'))
        self.config = dict(paths=dict(exports_invoices=str(self.case.root)),
                           email_smtp=dict(host='127.0.0.1', port=8025,
                                           security='LOCAL', sender='sender@example.test'))

    def pending_mail(self):
        f = self.case
        picking, lid, orders = f.allocated()
        picking.start_list(lid)
        for line in picking.get_list(lid)['lines']:
            picking.confirm_pick(line['allocation_id'], line['quantity'])
        picking.close_list(lid)
        order = orders[1]
        dispatch = DispatchController(f.path)
        item = dispatch.packing_lines(order)[0]['item_id']
        shipment = dispatch.add_parcel(order, 'CUSTOM_BOX', 1, {item: 2})
        dispatch.add_parcel(order, 'CUSTOM_BOX', 1, {item: 2})
        dispatch.confirm((f'ORD-{order:05d}', str(shipment), 'REVIEW-TRACK'), {}, 'en')
        return order, shipment

    def assert_mail_denied(self, mail, shipment, error):
        before = self.case.snapshot()
        with patch('smtplib.SMTP') as smtp, patch('smtplib.SMTP_SSL') as tls:
            with self.assertRaisesRegex(AuthError, error):
                mail.send(shipment, self.config, self.t)
        smtp.assert_not_called()
        tls.assert_not_called()
        self.assertEqual(before, self.case.snapshot())

    def test_mail_rejects_logged_out_temporary_password_and_stale_contexts(self):
        f = self.case
        _, shipment = self.pending_mail()
        previous = DispatchMail(f.path)
        f.auth.sign_out()
        self.assert_mail_denied(previous, shipment, 'auth_required')
        self.assert_mail_denied(DispatchMail(f.path), shipment, 'auth_required')
        with patch.object(auth_controller, 'runtime', None):
            self.assert_mail_denied(DispatchMail(f.path), shipment, 'auth_required')
        f.auth.sign_in('admin', 'administrator-secret')
        self.assert_mail_denied(previous, shipment, 'auth_required')
        current = DispatchMail(f.path)
        other = f.registry.create(f.root / 'other.db')
        f.auth.warehouse = f.registry.activate(other)
        self.assert_mail_denied(current, shipment, 'warehouse_context_changed')
        f.auth.warehouse = f.path
        f.auth.create_account('employee', 'temporary')
        f.auth.sign_in('employee', 'temporary')
        self.assert_mail_denied(DispatchMail(f.path), shipment, 'auth_change_required')
        f.auth.change_password('temporary', 'own-secret')
        with patch('smtplib.SMTP') as smtp:
            self.assertEqual(DispatchMail(f.path).send(shipment, self.config, self.t), 'sent')
            smtp.return_value.send_message.assert_called_once()

    def test_worker_rechecks_session_and_can_send_for_current_employee(self):
        f = self.case
        _, shipment = self.pending_mail()
        worker = MailWorker(f.path, [shipment, shipment + 100], self.config, self.t, (), None)
        results = []
        worker.result.connect(lambda sid, state: results.append((sid, state)))
        before = f.snapshot()
        f.auth.sign_out()
        with patch('smtplib.SMTP') as smtp:
            worker.start()
            self.assertTrue(worker.wait(5000))
            smtp.assert_not_called()
        self.app.processEvents()
        self.assertEqual(results, [(shipment, 'auth_required')])
        self.assertEqual(before, f.snapshot())
        f.auth.sign_in('admin', 'administrator-secret')
        f.employee()
        worker = MailWorker(f.path, [shipment], self.config, self.t, (), None)
        with patch('smtplib.SMTP') as smtp:
            worker.start()
            self.assertTrue(worker.wait(5000))
            smtp.return_value.send_message.assert_called_once()
        self.assertEqual(DispatchMail(f.path).get(shipment)['state'], 'sent')

    def test_revocation_before_transport_restores_unsubmitted_job(self):
        f = self.case
        _, shipment = self.pending_mail()
        for phase in ('render', 'connect'):
            with self.subTest(phase=phase):
                f.auth.sign_in('admin', 'administrator-secret')
                mail = DispatchMail(f.path)
                before = f.snapshot()
                render = mail.preview

                def revoke_after_render(*args):
                    rendered = render(*args)
                    f.auth.sign_out()
                    return rendered

                with patch('smtplib.SMTP') as smtp:
                    if phase == 'connect':
                        def revoke_on_connect(*args, **kwargs):
                            f.auth.sign_out()
                            return smtp.return_value
                        smtp.side_effect = revoke_on_connect
                    with patch.object(mail, 'preview', side_effect=revoke_after_render if phase == 'render' else render):
                        with self.assertRaises(AuthError):
                            mail.send(shipment, self.config, self.t)
                    smtp.return_value.send_message.assert_not_called()
                    if phase == 'render':
                        smtp.assert_not_called()
                self.assertEqual(before, f.snapshot())

    def test_registration_and_activation_reject_missing_operational_columns(self):
        f = self.case
        for table, column in (('dict_shipping_methods', 'service_name_en'),
                              ('dict_package_types', 'max_weight'),
                              ('orders', 'delivery_second_name'),
                              ('packages', 'actual_weight'),
                              ('dispatch_mail', 'message'),
                              ('dispatch_mail', 'claimed_at')):
            with self.subTest(table=table, column=column):
                target = f.root / f'{table}-{column}.db'
                with closing(sqlite3.connect(f.path)) as source, closing(sqlite3.connect(target)) as dest:
                    source.backup(dest)
                    dest.execute(f'ALTER TABLE {table} DROP COLUMN {column}')
                    dest.commit()
                before = target.read_bytes()
                paths = f.registry.paths()
                with self.assertRaisesRegex(ValueError, 'warehouse_invalid'):
                    f.registry.register(target)
                self.assertEqual(target.read_bytes(), before)
                self.assertEqual(f.registry.paths(), paths)
                # A file can also become incompatible after it was registered.
                with closing(f.auth.connect()) as db, db:
                    db.execute('INSERT INTO warehouses(path) VALUES(?)', (str(target),))
                with self.assertRaisesRegex(ValueError, 'warehouse_invalid'):
                    f.registry.activate(target)
                self.assertEqual(f.auth.warehouse, f.path)

    def test_pre_v7_warehouse_registration_preserves_data_and_adds_history_schema(self):
        f = self.case
        target = f.root / 'pre-v7.db'
        with closing(sqlite3.connect(f.path)) as source, closing(sqlite3.connect(target)) as dest:
            source.backup(dest)
            dest.executescript('DROP TABLE operation_history; DROP TABLE delivery_receipts; '
                               'ALTER TABLE locations DROP COLUMN is_archived;')
        products = f.sql('SELECT * FROM products', path=target)
        stock = f.sql('SELECT * FROM inventory', path=target)
        self.assertEqual(f.registry.register(target), str(target))
        self.assertEqual(f.sql('SELECT * FROM products', path=target), products)
        self.assertEqual(f.sql('SELECT * FROM inventory', path=target), stock)
        self.assertEqual(f.sql('SELECT operation FROM operation_history', path=target), [('WAREHOUSE_REGISTER',)])

    def test_failed_switch_to_incompatible_registered_file_keeps_current_window(self):
        from views.session_host import SessionHost
        f = self.case
        target = f.registry.create(f.root / 'damaged-after-registration.db')
        with closing(sqlite3.connect(target)) as db, db:
            db.execute('ALTER TABLE dict_shipping_methods DROP COLUMN service_name_en')
        config = dict(paths=dict(database=f.path, accounts=f.auth.path),
                      localization=dict(language='en'), appearance=dict(theme='light'))
        with patch('views.session_host.QTimer.singleShot'):
            host = SessionHost(config, self.t)
        self.addCleanup(host.close)
        host.auth.sign_in('admin', 'administrator-secret')
        host.install(f.path)
        host.set_access(True)
        original = host.main
        host.warehouses.setCurrentIndex(host.warehouses.findData(target))
        with patch.object(host, 'discard', return_value=True), patch('views.session_host.QMessageBox.warning') as warning:
            host.switch()
        self.assertIs(host.main, original)
        self.assertEqual(host.auth.warehouse, f.path)
        self.assertEqual(host.auth.active_warehouse(), f.path)
        self.assertEqual(host.warehouses.currentData(), f.path)
        self.assertEqual(warning.call_args.args[2], self.t.t('warehouse_invalid'))
        self.assertTrue(host.main.product_ctrl.get_products())

    def test_packing_refresh_and_worker_completion_do_not_restore_smtp_feedback(self):
        f = self.case
        order, shipment = self.pending_mail()
        f.sql("UPDATE dispatch_mail SET state='failed',detail='smtp_setup' WHERE shipment_id=?", (shipment,))
        dialog = DispatchDialog(self.t, f.path, order, confirm=True)
        self.addCleanup(dialog.close)
        dialog.parcel_table.selectRow(0)
        self.assertIn('SMTP', dialog.message.text())
        dialog.tabs.setCurrentIndex(0)
        self.assertEqual(dialog.message.text(), '')
        dialog.clear_draft()
        self.assertEqual(dialog.message.text(), '')
        dialog.mail_result(shipment, 'failed')
        self.assertEqual(dialog.message.text(), '')
        dialog.tabs.setCurrentIndex(1)
        self.assertIn('SMTP', dialog.message.text())
        dialog.parcel_table.selectRow(1)
        self.assertEqual(dialog.message.text(), '')


if __name__ == '__main__':
    unittest.main()
