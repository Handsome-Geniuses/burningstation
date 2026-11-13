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
    def test_unsupervised_call_in_rejected_before_meter_controls(self):
        meter = SimpleNamespace(host='192.0.2.14', goto_callin=Mock(), press=Mock())
        with self.assertRaisesRegex(RuntimeError, 'requires an active meter supervisor'):
            call_in._run_call_in_cycle(meter, SharedState(), 1, {}, {}, 0)
        meter.goto_callin.assert_not_called()
        meter.press.assert_not_called()

    def test_disconnected_supervisor_journal_blocks_plus(self):
        meter = SimpleNamespace(host='192.0.2.15', goto_callin=Mock(), press=Mock())
        session = MeterSession(meter)
        session.supervisor = object()
        meter.session = session
        session.mark_ready()
        with self.assertRaisesRegex(call_in.CallInObservationError, 'supervisor journal capture'):
            call_in._run_call_in_cycle(
                meter, SharedState(), 1, {}, {'ready_timeout_s': 0}, 0,
            )
        meter.goto_callin.assert_not_called()
        meter.press.assert_not_called()

    def test_precheck_requires_stable_ready_page_before_press(self):
        status = ('CIM: state=S1_WAITING_FOR_CALL_TIME\nCS: state=S5_DISCONNECTED\n'
                  'MODEM: state=S1_IDLE\nClients requesting connection: (none)')
        meter = SimpleNamespace(host='192.0.2.9', get_meter_status_text=Mock(return_value=status))
        shared = SharedState()
        clock = [0.0]
        ui_states = iter([('unknown', 'Loading'), ('ready', 'Press [+] to Call In.')])

        def ui_state(_meter):
            return next(ui_states, ('ready', 'Press [+] to Call In.'))

        def advance(_shared, _seconds):
            clock[0] += 1

        with patch.object(call_in.time, 'time', side_effect=lambda: clock[0]), \
             patch.object(call_in, '_sleep_with_stop', side_effect=advance), \
             patch.object(call_in, '_get_call_in_ui_state', side_effect=ui_state):
            _, elapsed = call_in._wait_for_call_in_idle(
                meter, shared, 1, timeout_s=10, poll_s=1, phase='pre-check',
                stable_s=3, require_ui_ready=True,
            )

        self.assertGreaterEqual(elapsed, 4)

    def test_journal_request_confirms_fast_call_in_when_cim_poll_misses_it(self):
        status = ('CIM: state=S1_WAITING_FOR_CALL_TIME\nCS: state=S5_DISCONNECTED\n'
                  'MODEM: state=S1_IDLE\nClients requesting connection: (none)')
        meter = SimpleNamespace(host='192.0.2.12', get_meter_status_text=Mock(return_value=status))
        shared = SharedState()
        snapshot, lifecycle, _ = call_in._wait_for_call_in_lifecycle(
            meter, shared, 1, start_timeout_s=20, completion_timeout_s=120,
            poll_s=2,
            request_started=lambda: True,
            proof_complete=lambda _observed, _snapshot: True,
        )
        self.assertEqual(snapshot['cim_state'], call_in.CALL_IN_READY_STATE)
        self.assertFalse(lifecycle['saw_cim_wait_connection'])
        self.assertEqual(meter.get_meter_status_text.call_count, 1)

    def test_supervised_cycle_uses_session_without_startup_wait(self):
        status = ('CIM: state=S1_WAITING_FOR_CALL_TIME\nCS: state=S5_DISCONNECTED\n'
                  'MODEM: state=S1_IDLE\nClients requesting connection: (none)')
        meter = SimpleNamespace(host='192.0.2.8', hostname='30005989',
                                goto_callin=Mock(), press=Mock())
        session = MeterSession(meter)
        session.supervisor = object()
        session.journal_connected = True
        meter.session = session
        session.mark_ready()
        shared = SharedState()
        baseline = call_in._parse_meter_status(status)
        settings = dict(ready_timeout_s=120, ready_stable_s=3, poll_s=2)
        meta = {}

        with patch.object(call_in, '_wait_for_call_in_idle', return_value=(baseline, 0)), \
             patch.object(call_in, '_complete_managed_call_in_cycle') as complete:
            call_in._run_call_in_cycle(meter, shared, 1, meta, settings, 0)

        complete.assert_called_once()
        self.assertNotIn('startup_guard_source', meta)
        self.assertEqual(meta['phase'], 'start_call_in')
        meter.press.assert_called_once_with('plus')

    def test_restriction_after_precheck_does_not_send_plus(self):
        status = ('CIM: state=S1_WAITING_FOR_CALL_TIME\nCS: state=S5_DISCONNECTED\n'
                  'MODEM: state=S1_IDLE\nClients requesting connection: (none)')
        meter = SimpleNamespace(host='192.0.2.13', goto_callin=Mock(), press=Mock())
        session = MeterSession(meter)
        session.supervisor = object()
        session.journal_connected = True
        meter.session = session
        session.mark_ready()
        shared = SharedState()
        baseline = call_in._parse_meter_status(status)
        settings = dict(ready_timeout_s=120, ready_stable_s=3, poll_s=2)

        def precheck(*_args, **_kwargs):
            session.interrupt('MS3 applying an update', phase='updating')
            return baseline, 0

        with patch.object(call_in, '_wait_for_call_in_idle', side_effect=precheck):
            with self.assertRaises(MeterInterrupted):
                call_in._run_call_in_cycle(meter, shared, 1, {}, settings, 0)
        meter.press.assert_not_called()
        self.assertNotIn('call_in_in_flight', shared.extras)
        self.assertEqual(session.subscribers, set())

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
        session.journal_connected = True
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
                subscriber.log('systemd[1]: Stopping MS3 Platform...',
                               source='supervisor.journal', persist=False)

        meter.press = Mock(side_effect=press)
        baseline = call_in._parse_meter_status(status)
        observed = call_in._new_lifecycle()
        observed['saw_cs_connected'] = True
        with patch.object(call_in, '_wait_for_call_in_idle', return_value=(baseline, 0)), \
             patch.object(call_in, '_wait_for_call_in_lifecycle', return_value=(None, observed, 1)), \
             patch.object(session, 'wait_ready', side_effect=lambda *a, **k: session.epoch if session.ready else self.fail('waited for update recovery')):
            run_subtest(meter, shared, 'call in',
                        lambda: call_in.test_cycle_call_in(meter, shared, job_count=1, subtest=True))

        meta = shared.device_meta['call_in'][1]
        self.assertEqual(meta['status'], 'pass')
        self.assertEqual(meta['evidence_source'], 'supervisor_journal')
        self.assertEqual(meta['platform_evidence']['call_in_reference'], 1054)
        self.assertFalse(session.ready)
        self.assertTrue(meta['update_or_config_downloaded'])
        self.assertTrue(meta['restart_detected'])
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

    def test_transfer_and_restart_intent_are_not_download_or_restart_proof(self):
        platform = call_in._collect_platform_call_in_evidence('\n'.join([
            'SAGENT SEND: {"command":"callIn", "reference":123}',
            'SAGENT RECV: {"message":"Rsync Completed"}',
            'SAGENT RECV: {"message":"Session Manager Completed"}',
            'SAGENT RECV: {"command":"callInResponse", "reference":123}',
            'Updater:UpdaterCheckForUpdates: invoking update (systemctl restart MS3_RunOnce)',
        ]))
        self.assertTrue(platform['rsync_completed'])
        self.assertTrue(platform['update_restart'])
        self.assertFalse(platform['update_or_config_downloaded'])
        self.assertFalse(platform['restart_started'])

    def test_ready_return_without_send_closes_manual_window(self):
        meter = SimpleNamespace(host='192.0.2.3', hostname='30005774')
        session = MeterSession(meter)
        session.supervisor = object()
        session.journal_connected = True
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
                        disconnect_timeout_s=45, poll_s=2,
                        transition_observe_s=0)
        with patch.object(call_in, '_wait_for_call_in_lifecycle',
                          return_value=(baseline, observed, 7)), \
             patch.object(call_in, '_wait_for_call_in_idle', return_value=(baseline, 0)), \
             patch.object(call_in.time, 'monotonic', side_effect=count(0, 10)), \
             patch.object(call_in, '_sleep_with_stop'):
            with self.assertRaisesRegex(RuntimeError, 'missing SAgent callIn request'):
                call_in._complete_managed_call_in_cycle(
                    meter, shared, session, call_in._ManagedJournalCapture(),
                    1, meta, settings, baseline, 0,
                )
        self.assertTrue(meta['manual_window_closed_without_send'])
        self.assertEqual(meta['evidence_source'], 'supervisor_journal')

    def test_stable_supervised_call_in_waits_for_local_idle(self):
        meter = SimpleNamespace(host='192.0.2.4', hostname='30001189')
        session = MeterSession(meter)
        session.supervisor = object()
        session.journal_connected = True
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
                        disconnect_timeout_s=45, poll_s=2,
                        transition_observe_s=0)
        with patch.object(call_in, '_wait_for_call_in_lifecycle',
                          return_value=(busy, observed, 30)), \
             patch.object(call_in, '_wait_for_call_in_idle', return_value=(baseline, 12)) as idle:
            call_in._complete_managed_call_in_cycle(
                meter, shared, session, capture, 1, meta, settings,
                baseline, 0,
            )
        idle.assert_called_once()
        self.assertEqual(meta['status'], 'pass')
        self.assertEqual(meta['cleanup_elapsed_s'], 12)
        self.assertEqual(meta['effective_cleanup_source'], 'cleanup')
        self.assertFalse(meta['update_or_config_downloaded'])
        self.assertFalse(meta['restart_detected'])
        self.assertTrue(any('call-in cycle 1 DEBUG: stream_lines=' in line for line in shared.logs))

    def test_transition_window_catches_delayed_update_and_stops_before_recovery(self):
        meter = SimpleNamespace(host='192.0.2.10')
        session = MeterSession(meter)
        session.supervisor = object()
        session.journal_connected = True
        session.mark_ready()
        shared = SharedState()
        baseline = call_in._parse_meter_status(
            'CIM: state=S1_WAITING_FOR_CALL_TIME\nCS: state=S5_DISCONNECTED\n'
            'MODEM: state=S1_IDLE\nClients requesting connection: (none)'
        )
        capture = call_in._ManagedJournalCapture()
        for line in (
            'modem:sHandleConnectRequest: Requested to connect, State=S1_IDLE',
            'SAGENT SEND: {"command":"callIn", "reference":1106}',
            'SAGENT RECV: {"message":"Session Manager Completed"}',
            'Clients that need a connection: (none)',
            'SAGENT RECV: {"command":"callInResponse", "reference":1106}',
        ):
            capture.log(line, source='supervisor.journal')
        observed = call_in._new_lifecycle()
        observed['saw_cs_connected'] = True
        clock = [0.0]

        def advance(_shared, seconds):
            clock[0] += seconds
            if clock[0] >= 12 and clock[0] - seconds < 12:
                capture.log('Updater:UpdaterCheckForUpdates: Installing legacy config',
                            source='supervisor.journal')
                session.interrupt('MS3 applying an update', phase='updating')
            if clock[0] >= 14 and clock[0] - seconds < 14:
                capture.log('systemd[1]: Stopping MS3 Platform...', source='supervisor.journal')

        settings = dict(start_timeout_s=20, completion_timeout_s=120,
                        disconnect_timeout_s=45, poll_s=2,
                        transition_observe_s=20)
        meta = {'trigger_epoch': session.epoch}
        with patch.object(call_in, '_wait_for_call_in_lifecycle',
                          return_value=(None, observed, 1)), \
             patch.object(call_in.time, 'monotonic', side_effect=lambda: clock[0]), \
             patch.object(call_in, '_sleep_with_stop', side_effect=advance), \
             patch.object(call_in, '_wait_for_call_in_idle') as idle:
            call_in._complete_managed_call_in_cycle(
                meter, shared, session, capture, 1, meta, settings, baseline, 0,
            )
        idle.assert_not_called()
        self.assertEqual(meta['status'], 'pass')
        self.assertEqual(meta['transition_observed_s'], 14)
        self.assertTrue(meta['update_or_config_downloaded'])
        self.assertTrue(meta['restart_detected'])
        self.assertFalse(meta['transition_observation_complete'])

    def test_transition_window_without_update_records_false_after_full_window(self):
        meter = SimpleNamespace(host='192.0.2.11')
        session = MeterSession(meter)
        session.supervisor = object()
        session.journal_connected = True
        session.mark_ready()
        shared = SharedState()
        baseline = call_in._parse_meter_status(
            'CIM: state=S1_WAITING_FOR_CALL_TIME\nCS: state=S5_DISCONNECTED\n'
            'MODEM: state=S1_IDLE\nClients requesting connection: (none)'
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
        observed['saw_cs_connected'] = True
        clock = [0.0]
        settings = dict(start_timeout_s=20, completion_timeout_s=120,
                        disconnect_timeout_s=45, poll_s=2,
                        transition_observe_s=20)
        meta = {'trigger_epoch': session.epoch}

        def advance(_shared, seconds):
            clock[0] += seconds

        with patch.object(call_in, '_wait_for_call_in_lifecycle',
                          return_value=(None, observed, 1)), \
             patch.object(call_in.time, 'monotonic', side_effect=lambda: clock[0]), \
             patch.object(call_in, '_sleep_with_stop', side_effect=advance), \
             patch.object(call_in, '_wait_for_call_in_idle', return_value=(baseline, 0)) as idle:
            call_in._complete_managed_call_in_cycle(
                meter, shared, session, capture, 1, meta, settings, baseline, 0,
            )
        idle.assert_called_once()
        self.assertEqual(meta['status'], 'pass')
        self.assertEqual(meta['transition_observed_s'], 20)
        self.assertTrue(meta['transition_observation_complete'])
        self.assertFalse(meta['update_or_config_downloaded'])
        self.assertFalse(meta['restart_detected'])

    def test_missing_live_response_fails_without_waiting_for_new_runtime(self):
        meter = SimpleNamespace(host='192.0.2.5', hostname='30004914')
        session = MeterSession(meter)
        session.supervisor = object()
        session.journal_connected = True
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
        lifecycle = call_in._new_lifecycle()
        lifecycle.update(runtime_loss_after_start=True, saw_cs_connected=True)
        meta = {'trigger_epoch': original_epoch}
        settings = dict(start_timeout_s=20, completion_timeout_s=120,
                        disconnect_timeout_s=45, poll_s=2,
                        transition_observe_s=0)
        with patch.object(call_in, '_wait_for_call_in_lifecycle',
                          return_value=(None, lifecycle, 30)), \
             patch.object(call_in.time, 'monotonic', side_effect=count(0, 10)), \
             patch.object(call_in, '_sleep_with_stop'), \
             patch.object(session, 'wait_ready') as wait_ready:
            with self.assertRaisesRegex(RuntimeError, 'missing SAgent callInResponse'):
                call_in._complete_managed_call_in_cycle(
                    meter, shared, session, capture, 1, meta, settings,
                    baseline, 0,
                )
        wait_ready.assert_not_called()
        self.assertFalse(hasattr(call_in, '_get_service_journal'))
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
        session.supervisor = object()
        session.journal_connected = True
        meter.session = session
        session.mark_ready()
        shared = SharedState()
        shared.last_error = None
        presses = []

        def press(key):
            presses.append(key)
            for line in (
                'modem:sHandleConnectRequest: Requested to connect, State=S1_IDLE',
                'SAGENT SEND: {"command":"callIn", "reference":1027}',
                'SAGENT RECV: {"message":"Try Session Manager"}',
                'SAGENT RECV: {"message":"Session complete"}',
                'Clients that need a connection: (none)',
                'SAGENT RECV: {"command":"callInResponse", "reference":1027}',
                'UpdaterCheckForUpdates: Installing legacy config',
                'systemd[1]: Stopping MS3 Platform...',
                'SAGENT SEND: {"command":"callIn", "reference":1011}',
            ):
                for subscriber in tuple(session.subscribers):
                    subscriber.log(line, source='supervisor.journal')
            session.interrupt('restart during trigger', phase='restarting')
            raise MeterInterrupted('restart during trigger')

        meter.press = press
        lifecycle = call_in._new_lifecycle()
        lifecycle.update(runtime_loss_after_start=True, saw_cs_connected=True, saw_modem_connected=True)
        baseline = call_in._parse_meter_status(status)
        with patch.object(call_in, '_wait_for_call_in_idle', return_value=(baseline, 0)), \
             patch.object(call_in, '_wait_for_call_in_lifecycle', return_value=(None, lifecycle, 1)):
            run_subtest(meter, shared, 'call in', lambda: call_in.test_cycle_call_in(meter, shared, job_count=1))
        self.assertEqual(presses, ['plus'])
        meta = shared.device_meta['call_in'][1]
        self.assertEqual(meta['status'], 'pass')
        self.assertEqual(meta['platform_evidence']['call_in_reference'], 1027)
        self.assertTrue(meta['platform_evidence']['call_in_response'])
        self.assertTrue(meta['restart_detected'])
        self.assertNotIn('call_in_in_flight', shared.extras)
        self.assertFalse(shared.lifecycle_observer)


if __name__ == '__main__':
    unittest.main()
