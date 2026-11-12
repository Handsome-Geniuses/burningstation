"""A restart during the call-in trigger must preserve its original transaction."""
from importlib import import_module
from itertools import count
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from lib.automation.shared_state import SharedState
from lib.automation.recovery import run_subtest
from lib.meter.lifecycle import MeterSession, MeterInterrupted
from lib.store.settings import Settings


call_in = import_module('lib.automation.tests.cycle_call_in')
automation_settings = import_module('lib.automation.settings')


class ManagedCallInTests(unittest.TestCase):
    def test_passive_call_in_debug_setting_reaches_subtest(self):
        configured = Settings()
        self.assertFalse(configured.passive.call_in.debug)
        configured.passive.call_in.debug = True
        fake_store = SimpleNamespace(load=Mock(), settings=configured)
        with patch.object(automation_settings, 'store', fake_store):
            kwargs = automation_settings.build_passive_kwargs({'MK7_XE910': {}})
        self.assertEqual(kwargs['call in'], {'job_count': 1, 'debug': True})

        meter = SimpleNamespace(host='192.0.2.7')
        shared = SharedState()
        with patch.object(call_in, '_run_call_in_cycle') as run_cycle:
            call_in.test_cycle_call_in(meter, shared, job_count=1, subtest=True)
        self.assertFalse(run_cycle.call_args.kwargs['settings']['debug'])
        self.assertFalse(any('call-in cycle 1 DEBUG:' in line for line in shared.logs))

    def test_supervised_update_validates_before_readiness_returns(self):
        status = ('CIM: state=S1_WAITING_FOR_CALL_TIME\nCS: state=S5_DISCONNECTED\n'
                  'MODEM: state=S1_IDLE\nClients requesting connection: (none)')
        meter = SimpleNamespace(host='192.0.2.2', hostname='30005971', goto_callin=Mock())
        session = MeterSession(meter)
        session.admitted = True
        session.supervisor = object()
        meter.session = session
        session.mark_ready()
        shared = SharedState()
        shared.last_error = None

        def press(_key):
            lines = [
                'modem:sHandleConnectRequest: Requested to connect, State=S1_IDLE',
                'SAGENT SEND: {"command":"callIn", "reference":1054}',
                'SAGENT RECV: {"message":"Session Manager Completed"}',
                'ConnectionServer:CSSetIsConnectionNeeded: Clients that need a connection: (none)',
                'SAGENT RECV: {"command":"callInResponse", "reference":1054}',
            ]
            for line in lines:
                for subscriber in tuple(session.subscribers):
                    subscriber.log(line, source='supervisor.journal', persist=False)
            session.interrupt('MS3 applying an update', phase='updating')
            for subscriber in tuple(session.subscribers):
                subscriber.log('Updater:UpdaterCheckForUpdates: Installing legacy config',
                               source='supervisor.journal', persist=False)

        meter.press = Mock(side_effect=press)
        baseline = call_in._parse_meter_status(status)
        observed = call_in._new_lifecycle()
        observed['saw_cs_connected'] = True
        with patch.object(call_in, '_wait_for_call_in_idle', return_value=(baseline, 0)), \
             patch.object(call_in, '_journal_since_now', return_value='2026-10-20 07:52:25'), \
             patch.object(call_in, '_wait_for_call_in_lifecycle', return_value=(None, observed, 1)), \
             patch.object(session, 'wait_ready', side_effect=lambda *a, **k: session.epoch if session.ready else self.fail('waited for update recovery')):
            run_subtest(meter, shared, 'call in',
                        lambda: call_in.test_cycle_call_in(meter, shared, job_count=1, subtest=True))

        meta = shared.device_meta['call_in'][1]
        self.assertEqual(meta['status'], 'pass')
        self.assertEqual(meta['evidence_source'], 'supervisor_journal')
        self.assertEqual(meta['platform_evidence']['call_in_reference'], 1054)
        self.assertFalse(session.ready)
        self.assertEqual(meter.press.call_count, 1)
        self.assertFalse(shared.lifecycle_observer)
        self.assertEqual(session.subscribers, set())

    def test_release_marker_before_session_completion_is_not_proof(self):
        platform = call_in._collect_platform_call_in_evidence('\n'.join([
            'SAGENT SEND: {"command":"callIn", "reference":123}',
            'Clients that need a connection: (none)',
            'SAGENT RECV: {"message":"Session Manager Completed"}',
            'SAGENT RECV: {"command":"callInResponse", "reference":123}',
        ]))
        self.assertFalse(platform['clients_released_after_session'])

    def test_startup_call_in_cannot_supply_manual_release(self):
        platform, modem = call_in._managed_evidence('\n'.join([
            'modem:sHandleConnectRequest: Requested to connect, State=S1_IDLE',
            'SAGENT SEND: {"command":"callIn", "reference":123}',
            'SAGENT RECV: {"message":"Session Manager Completed"}',
            'SAGENT RECV: {"command":"callInResponse", "reference":123}',
            'SAGENT SEND: {"command":"callIn", "reference":1009}',
            'Clients that need a connection: (none)',
            'modem:State: From S4_CONNECTED to S1_IDLE',
        ]))
        self.assertEqual(platform['call_in_reference'], 123)
        self.assertFalse(platform['clients_released_after_session'])
        self.assertFalse(modem['idle_after_disconnect'])

    def test_later_active_client_revokes_platform_release(self):
        platform = call_in._collect_platform_call_in_evidence('\n'.join([
            'SAGENT SEND: {"command":"callIn", "reference":123}',
            'SAGENT RECV: {"message":"Session Manager Completed"}',
            'Clients that need a connection: (none)',
            'Clients that need a connection: RSYNC',
            'SAGENT RECV: {"command":"callInResponse", "reference":123}',
        ]))
        self.assertFalse(platform['clients_released_after_session'])

    def test_ready_return_without_send_closes_manual_window(self):
        meter = SimpleNamespace(host='192.0.2.3', hostname='30005774')
        session = MeterSession(meter)
        session.supervisor = object()
        session.mark_ready()
        shared = SharedState()
        baseline = call_in._parse_meter_status(
            'CIM: state=S1_WAITING_FOR_CALL_TIME\nCS: state=S5_DISCONNECTED\n'
            'MODEM: state=S1_IDLE\nClients requesting connection: (none)'
        )
        observed = call_in._new_lifecycle()
        observed.update(saw_cim_wait_connection=True, saw_ready_return=True)
        meta = {}
        settings = dict(start_timeout_s=20, completion_timeout_s=120,
                        disconnect_timeout_s=45, poll_s=2, status_loss_grace_s=8)
        with patch.object(call_in, '_wait_for_call_in_lifecycle',
                          return_value=(baseline, observed, 7)), \
             patch.object(call_in, '_wait_for_call_in_idle', return_value=(baseline, 0)), \
             patch.object(call_in.time, 'monotonic', side_effect=count(0, 10)), \
             patch.object(call_in, '_sleep_with_stop'):
            with self.assertRaisesRegex(RuntimeError, 'missing SAgent callIn request'):
                call_in._complete_managed_call_in_cycle(
                    meter, shared, session, call_in._ManagedJournalCapture(),
                    1, meta, settings, baseline, '2026-10-27 12:39:10', 0,
                )
        self.assertTrue(meta['manual_window_closed_without_send'])
        self.assertEqual(meta['evidence_source'], 'supervisor_journal')

    def test_stable_supervised_call_in_waits_for_local_idle(self):
        meter = SimpleNamespace(host='192.0.2.4', hostname='30001189')
        session = MeterSession(meter)
        session.supervisor = object()
        session.mark_ready()
        shared = SharedState()
        baseline = call_in._parse_meter_status(
            'CIM: state=S1_WAITING_FOR_CALL_TIME\nCS: state=S5_DISCONNECTED\n'
            'MODEM: state=S1_IDLE\nClients requesting connection: (none)'
        )
        busy = call_in._parse_meter_status(
            'CIM: state=S1_WAITING_FOR_CALL_TIME\nCS: state=S3_CONNECTED\n'
            'MODEM: state=S4_CONNECTED\nClients requesting connection: RSYNC'
        )
        capture = call_in._ManagedJournalCapture()
        for line in (
            'modem:sHandleConnectRequest: Requested to connect, State=S1_IDLE',
            'SAGENT SEND: {"command":"callIn", "reference":1011}',
            'SAGENT RECV: {"message":"Session Manager Completed"}',
            'Clients that need a connection: (none)',
            'SAGENT RECV: {"command":"callInResponse", "reference":1011}',
        ):
            capture.log(line, source='supervisor.journal')
        observed = call_in._new_lifecycle()
        observed.update(saw_ready_return=True, saw_cs_connected=True)
        meta = {}
        settings = dict(debug=True, start_timeout_s=20, completion_timeout_s=120,
                        disconnect_timeout_s=45, poll_s=2, status_loss_grace_s=8)
        with patch.object(call_in, '_wait_for_call_in_lifecycle',
                          return_value=(busy, observed, 30)), \
             patch.object(call_in, '_wait_for_call_in_idle', return_value=(baseline, 12)) as idle:
            call_in._complete_managed_call_in_cycle(
                meter, shared, session, capture, 1, meta, settings,
                baseline, '2026-11-11 14:31:18', 0,
            )
        idle.assert_called_once()
        self.assertEqual(meta['status'], 'pass')
        self.assertEqual(meta['cleanup_elapsed_s'], 12)
        self.assertEqual(meta['effective_cleanup_source'], 'cleanup')
        self.assertTrue(any('call-in cycle 1 DEBUG: stream_lines=' in line for line in shared.logs))

    def test_fallback_rejects_startup_request_after_restart(self):
        meter = SimpleNamespace(host='192.0.2.5', hostname='30004914')
        session = MeterSession(meter)
        session.supervisor = object()
        session.mark_ready()
        original_epoch = session.epoch
        session.interrupt('MS3 applying an update', phase='updating')
        shared = SharedState()
        baseline = call_in._parse_meter_status(
            'CIM: state=S1_WAITING_FOR_CALL_TIME\nCS: state=S5_DISCONNECTED\n'
            'MODEM: state=S1_IDLE\nClients requesting connection: (none)'
        )
        capture = call_in._ManagedJournalCapture()
        capture.log('modem:sHandleConnectRequest: Requested to connect, State=S1_IDLE',
                    source='supervisor.journal')
        capture.log('SAGENT SEND: {"command":"callIn", "reference":123}',
                    source='supervisor.journal')
        startup = '\n'.join([
            'SAGENT SEND: {"command":"callIn", "reference":1009}',
            'SAGENT RECV: {"message":"Session Manager Completed"}',
            'Clients that need a connection: (none)',
            'SAGENT RECV: {"command":"callInResponse", "reference":1009}',
        ])
        lifecycle = call_in._new_lifecycle()
        lifecycle.update(runtime_loss_after_start=True, saw_cs_connected=True)
        meta = {'trigger_epoch': original_epoch}
        settings = dict(start_timeout_s=20, completion_timeout_s=120,
                        disconnect_timeout_s=45, poll_s=2, status_loss_grace_s=8,
                        recovery_timeout_s=300, platform_journal_max_lines=1500,
                        modem_journal_max_lines=100)
        with patch.object(call_in, '_wait_for_call_in_lifecycle',
                          return_value=(None, lifecycle, 30)), \
             patch.object(call_in.time, 'monotonic', side_effect=count(0, 10)), \
             patch.object(call_in, '_sleep_with_stop'), \
             patch.object(session, 'wait_ready', return_value=session.epoch), \
             patch.object(call_in, '_get_service_journal',
                          side_effect=lambda *a, **k: startup if a[1] == 'MS3_Platform.service' else ''):
            with self.assertRaisesRegex(RuntimeError, 'missing SAgent callInResponse'):
                call_in._complete_managed_call_in_cycle(
                    meter, shared, session, capture, 1, meta, settings,
                    baseline, '2026-10-06 07:18:43', 0,
                )
        self.assertEqual(meta['evidence_source'], 'supervisor_journal')
        self.assertEqual(meta['platform_evidence']['call_in_reference'], 123)

    def test_pretrigger_interruption_retries_only_current_iteration(self):
        meter = SimpleNamespace(host='192.0.2.6', hostname='30005971')
        session = MeterSession(meter)
        meter.session = session
        session.mark_ready()
        shared = SharedState()
        attempts = []

        def run_cycle(_meter, _shared, *, cycle_num, cycle_meta, **_kwargs):
            attempts.append(cycle_num)
            if attempts == [1, 2]:
                session.interrupt('MS3 update', phase='updating')
                session.mark_ready()
                raise MeterInterrupted('MS3 update', session.epoch)
            cycle_meta.update(status='pass', phase='complete')

        with patch.object(call_in, '_run_call_in_cycle', side_effect=run_cycle):
            call_in.test_cycle_call_in(meter, shared, job_count=2, subtest=True)

        self.assertEqual(attempts, [1, 2, 2])
        self.assertEqual(shared.device_meta['call_in'][1]['status'], 'pass')
        self.assertEqual(shared.device_meta['call_in'][2]['pretrigger_restarts'], 1)

    def test_observer_exemption_ends_before_next_iteration(self):
        meter = SimpleNamespace(host='192.0.2.1')
        shared = SharedState()
        observed_at_start = []

        def run_cycle(_meter, state, **_kwargs):
            observed_at_start.append(state.lifecycle_observer)
            state.lifecycle_observer = True

        with patch.object(call_in, '_run_call_in_cycle', side_effect=run_cycle):
            call_in.test_cycle_call_in(meter, shared, job_count=2, subtest=True)

        self.assertEqual(observed_at_start, [False, False])
        self.assertFalse(shared.lifecycle_observer)

    def test_trigger_interruption_continues_original_transaction(self):
        status = 'CIM: state=S1_WAITING_FOR_CALL_TIME\nCS: state=S5_DISCONNECTED\nMODEM: state=S1_IDLE\nClients requesting connection: (none)'
        meter = SimpleNamespace(host='192.0.2.1', hostname='30001189', goto_callin=Mock(),
                                get_meter_status_text=Mock(return_value=status))
        session = MeterSession(meter)
        session.admitted = True
        meter.session = session
        session.mark_ready()
        shared = SharedState()
        shared.last_error = None
        presses = []

        def press(key):
            presses.append(key)
            session.interrupt('restart during trigger')
            session.mark_ready()
            raise MeterInterrupted('restart during trigger')

        meter.press = press
        lifecycle = call_in._new_lifecycle()
        lifecycle.update(runtime_loss_after_start=True, saw_cs_connected=True, saw_modem_connected=True)
        journal = '\n'.join([
            'SAGENT SEND: {"command":"callIn", "reference":1027}',
            'SAGENT RECV: {"message":"Try Session Manager"}',
            'SAGENT RECV: {"command":"callInResponse", "reference":1027}',
            'SAGENT RECV: {"message":"Session complete"}',
            'UpdaterCheckForUpdates: Restarting, to use new legacy config',
            'SAGENT SEND: {"command":"callIn", "reference":1011}',
            'SAGENT RECV: {"command":"callInResponse", "reference":1011}',
        ])
        baseline = call_in._parse_meter_status(status)
        with patch.object(call_in, '_wait_for_call_in_idle', return_value=(baseline, 0)), \
             patch.object(call_in, '_journal_since_now', return_value='2026-11-06 08:00:00'), \
             patch.object(call_in, '_wait_for_call_in_lifecycle', return_value=(None, lifecycle, 1)), \
             patch.object(call_in, '_get_service_journal', side_effect=lambda *a, **k: journal if k['service'] == 'MS3_Platform.service' else ''):
            run_subtest(meter, shared, 'call in', lambda: call_in.test_cycle_call_in(meter, shared, job_count=1))
        self.assertEqual(presses, ['plus'])
        meta = shared.device_meta['call_in'][1]
        self.assertEqual(meta['status'], 'pass')
        self.assertEqual(meta['platform_evidence']['call_in_reference'], 1027)
        self.assertTrue(meta['platform_evidence']['call_in_response'])
        self.assertNotIn('call_in_in_flight', shared.extras)
        self.assertFalse(shared.lifecycle_observer)


if __name__ == '__main__':
    unittest.main()
