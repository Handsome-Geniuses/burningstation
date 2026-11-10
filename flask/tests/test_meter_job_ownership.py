"""Job leases cover cancellation and finalization, using offline fake meters."""
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from lib.automation import jobs
from lib.meter.lifecycle import MeterSession


class JobOwnershipTests(unittest.TestCase):
    def fixture(self, host):
        meter = SimpleNamespace(host=host, hostname='30001189', status='ready', results={},
                                db_id=None, connect=Mock(), get_info=Mock(return_value={}),
                                beep=Mock(), public_info=Mock(return_value={}))
        session = MeterSession(meter)
        session.admitted = True
        meter.session = session
        session.mark_ready()
        return meter, session

    def test_cancel_keeps_owner_until_worker_and_finalizer_end(self):
        meter, session = self.fixture('job-cancel')
        entered, finish = threading.Event(), threading.Event()

        def run(*args, **kwargs):
            entered.set()
            self.assertTrue(finish.wait(3))

        with patch.dict(jobs.mm.meters, {meter.host: meter}, clear=True), \
             patch.object(jobs, 'run_test_job', side_effect=run), \
             patch.object(jobs, 'job_done') as done, patch.object(jobs, '_handle_auto_job_done'):
            ok, _ = jobs.start_job(meter.host, 'dummy', {}, log=False)
            self.assertTrue(ok)
            self.assertTrue(entered.wait(2))
            jobs.stop_job(meter.host)
            self.assertIsNotNone(session.owner)
            self.assertFalse(session.claim('replacement'))
            self.assertFalse(jobs.start_job(meter.host, 'dummy', {}, log=False)[0])
            finish.set()
            jobs._threads[meter.host].join(3)
            self.assertFalse(jobs._threads[meter.host].is_alive())
            self.assertIsNone(session.owner)
            self.assertEqual(jobs._state(meter.host).status, 'cancelled')
            done.assert_called_once()

    def test_result_display_finalization_still_owns_meter(self):
        meter, session = self.fixture('job-finalization')
        finalizing, finish = threading.Event(), threading.Event()

        def done(*args, **kwargs):
            finalizing.set()
            self.assertIsNotNone(session.owner)
            self.assertTrue(finish.wait(3))

        with patch.dict(jobs.mm.meters, {meter.host: meter}, clear=True), \
             patch.object(jobs, 'run_test_job'), patch.object(jobs, 'job_done', side_effect=done), \
             patch.object(jobs, '_handle_auto_job_done'):
            self.assertTrue(jobs.start_job(meter.host, 'dummy', {}, log=False)[0])
            self.assertTrue(finalizing.wait(2))
            self.assertFalse(session.claim('next-job'))
            finish.set()
            jobs._threads[meter.host].join(3)
            self.assertIsNone(session.owner)

    def test_busy_meter_rejects_start_before_any_preparation(self):
        meter, session = self.fixture('job-preparation')
        session.owner = 'existing-job'
        prepare = Mock()
        with patch.dict(jobs.mm.meters, {meter.host: meter}, clear=True):
            self.assertFalse(jobs.start_job(meter.host, 'dummy', {}, log=False, prepare=prepare)[0])
        prepare.assert_not_called()
        self.assertEqual(session.owner, 'existing-job')

    def test_preparation_runs_once_under_job_ownership_before_worker(self):
        meter, session = self.fixture('owned-preparation')
        stages = []
        def prepare(meter):
            self.assertIsNotNone(session.owner)
            self.assertFalse(session.claim('supervisor'))
            stages.append('prepare')
            return {'prepared_option': 7}
        def run(meter, program, kwargs, shared, **options):
            self.assertEqual(kwargs['prepared_option'], 7)
            stages.append('worker')
        with patch.dict(jobs.mm.meters, {meter.host: meter}, clear=True), \
             patch.object(jobs, 'run_test_job', side_effect=run), patch.object(jobs, 'job_done'), \
             patch.object(jobs, '_handle_auto_job_done'):
            self.assertTrue(jobs.start_job(meter.host, 'dummy', {}, log=False, prepare=prepare)[0])
            jobs._threads[meter.host].join(3)
        self.assertEqual(stages, ['prepare', 'worker'])
        self.assertIsNone(session.owner)

    def test_results_are_shown_before_a_database_failure(self):
        order = []
        meter = SimpleNamespace(host='db-outage', hostname='30001189', results={},
                                db_id=42, module_info={},
                                update_display_results=Mock(side_effect=lambda st: order.append('display')))
        state = jobs.JobState(meter.host)
        state.current_program = 'cycle_all'
        def insert(*args):
            order.append('database')
            raise RuntimeError('database unavailable')
        with patch.object(jobs, 'insert_meter_jobs', side_effect=insert), \
             patch.object(jobs.master, 'publish_activity'):
            with self.assertRaisesRegex(RuntimeError, 'database unavailable'):
                jobs.job_done(meter.host, meter=meter, st=state)
        self.assertEqual(order, ['display', 'database'])

    def test_failed_job_setup_reports_error_and_releases_lease(self):
        meter, session = self.fixture('job-setup-error')
        meter.get_info.side_effect = RuntimeError('inventory read failed')

        with patch.dict(jobs.mm.meters, {meter.host: meter}, clear=True), \
             patch.object(jobs, '_handle_auto_job_done'):
            with self.assertRaisesRegex(RuntimeError, 'inventory read failed'):
                jobs.start_job(meter.host, 'dummy', {}, log=False)
            state = jobs._state(meter.host)
            self.assertEqual((state.status, state.result), ('error', 'fail'))
            self.assertEqual(state.last_error, 'inventory read failed')
            self.assertEqual(state.current_program, 'dummy')
            self.assertIsNone(session.owner)
            self.assertIsNone(session.shared)
            self.assertNotIn(meter.host, jobs._threads)

    def test_short_scan_miss_keeps_frontend_registration(self):
        from lib.meter.meter_manager import METERMANAGER as mm
        meter = SimpleNamespace(status='ready', close=Mock(), hostname='30001189')
        with patch.object(mm, 'meters', {'short-miss': meter}), \
             patch.object(mm, '_METERMANAGER__meters', {'short-miss'}), \
             patch.object(mm, '_METERMANAGER__stale_counts', {}), \
             patch('lib.meter.meter_manager.SSEQM.broadcast') as broadcast:
            mm.stale_meter('short-miss')
            self.assertIn('short-miss', mm.meters)
            self.assertFalse(any(c.args[0] == 'meter' and not c.args[1]['alive'] for c in broadcast.call_args_list))

    def test_repeated_scan_misses_do_not_interrupt_a_busy_healthy_session(self):
        from lib.meter.meter_manager import METERMANAGER as manager
        meter, session = self.fixture('busy-scan-miss')
        meter.status = 'busy'
        session.owner = 'existing-job'
        with patch.object(manager, 'meters', {meter.host: meter}), \
             patch.object(manager, '_METERMANAGER__meters', {meter.host}), \
             patch.object(manager, '_METERMANAGER__stale_counts', {}), \
             patch('lib.meter.meter_manager.SSEQM.broadcast') as broadcast:
            manager.stale_meter(meter.host)
            manager.stale_meter(meter.host)
            self.assertIn(meter.host, manager.meters)
            self.assertTrue(session.ready)
            self.assertEqual(session.epoch, 0)
            broadcast.assert_not_called()

    def test_known_sleep_is_retained_when_recovery_requires_intervention(self):
        from lib.meter.meter_manager import METERMANAGER as mm
        meter, session = self.fixture('sleeping')
        session.interrupt('Grace period timeout', phase='sleep')
        session.interrupt('Recovery timed out; wake the meter', phase='intervention')
        with patch.object(mm, 'meters', {meter.host: meter}), \
             patch.object(mm, '_METERMANAGER__meters', {meter.host}), \
             patch.object(mm, '_METERMANAGER__stale_counts', {}), \
             patch('lib.meter.meter_manager.SSEQM.broadcast') as broadcast:
            mm.stale_meter(meter.host)
            mm.stale_meter(meter.host)
            self.assertIn(meter.host, mm.meters)
            broadcast.assert_not_called()
        session.mark_ready()
        self.assertFalse(session.sleep_pending)

    def test_idle_disconnect_is_removed_and_reappearance_is_reidentified(self):
        from lib.meter.meter_manager import METERMANAGER as manager
        meter = SimpleNamespace(host='reappearing', hostname='30001189', status='ready',
                                close=Mock(), close_if_idle=Mock())
        with patch.object(manager, 'meters', {meter.host: meter}), \
             patch.object(manager, '_METERMANAGER__meters', {meter.host}), \
             patch.object(manager, '_METERMANAGER__stale_counts', {}), \
             patch.object(manager, '_METERMANAGER__attempts', {}), \
             patch.object(manager, '_METERMANAGER__retry_at', {}), \
             patch.object(manager, '_METERMANAGER__reachable', set()), \
             patch.object(manager, '_METERMANAGER__inflight', set()), \
             patch.object(manager, '_METERMANAGER__newly_ready', set()), \
             patch('lib.meter.meter_manager.ip_scanner.get_ips',
                   side_effect=[set(), set(), {meter.host}]), \
             patch.object(manager._METERMANAGER__workers, 'submit') as submit, \
             patch('lib.meter.meter_manager.SSEQM.broadcast') as broadcast:
            manager.refresh()
            self.assertIn(meter.host, manager.list_meters())
            manager.refresh()
            self.assertNotIn(meter.host, manager.list_meters())
            self.assertNotIn(meter.host, manager.meters)
            meter.close.assert_called_once()
            self.assertTrue(any(c.args[0] == 'meter' and not c.args[1]['alive']
                                for c in broadcast.call_args_list))
            manager.refresh()
            submit.assert_called_once()
            self.assertEqual(submit.call_args.args[1], meter.host)

    def test_sleep_wake_keeps_same_registered_session(self):
        from lib.meter.meter_manager import METERMANAGER as manager
        meter, session = self.fixture('sleep-wake')
        meter.close_if_idle = Mock()
        session.interrupt('Grace period timeout', phase='sleep')
        with patch.object(manager, 'meters', {meter.host: meter}), \
             patch.object(manager, '_METERMANAGER__meters', {meter.host}), \
             patch.object(manager, '_METERMANAGER__stale_counts', {}), \
             patch.object(manager, '_METERMANAGER__attempts', {}), \
             patch.object(manager, '_METERMANAGER__retry_at', {}), \
             patch.object(manager, '_METERMANAGER__reachable', set()), \
             patch.object(manager, '_METERMANAGER__inflight', set()), \
             patch.object(manager, '_METERMANAGER__newly_ready', set()), \
             patch('lib.meter.meter_manager.ip_scanner.get_ips',
                   side_effect=[set(), set(), {meter.host}]), \
             patch.object(manager._METERMANAGER__workers, 'submit') as submit, \
             patch('lib.meter.meter_manager.SSEQM.broadcast') as broadcast:
            manager.refresh()
            manager.refresh()
            self.assertIs(manager.get_meter(meter.host), meter)
            manager.refresh()
            self.assertIs(manager.get_meter(meter.host), meter)
            self.assertIs(meter.session, session)
            self.assertFalse(session.stopped.is_set())
            submit.assert_not_called()
            self.assertFalse(any(c.args[0] == 'meter' and not c.args[1]['alive']
                                 for c in broadcast.call_args_list))
            session.mark_ready()  # Stand in for the supervisor's post-wake proof.
            self.assertEqual(meter.status, 'ready')


if __name__ == '__main__':
    unittest.main()
