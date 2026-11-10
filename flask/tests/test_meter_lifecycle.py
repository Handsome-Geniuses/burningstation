"""Lifecycle/recovery behavior without network, database, or robot hardware."""
from pathlib import Path
from types import SimpleNamespace
import json
import threading
import time
import unittest
from unittest.mock import Mock, patch

from lib.meter.lifecycle import MeterSession, MeterInterrupted, RecoveryFailed
from lib.meter.supervisor import MeterSupervisor, transition_reason
from lib.automation.shared_state import SharedState
from lib.automation.helpers import check_stop_event, StopAutomation
from lib.automation.recovery import run_subtest


BOOT = "450199eb-a57b-40cd-8bcb-790fc84b7e29"
DIAGS = '<html><div class="diagTitle"><div>Service</div></div></html>'
HOME = '<html><title>Welcome</title>Pay to park</html>'
IDLE = 'CIM: state=S1_WAITING_FOR_CALL_TIME\nCS: state=S5_DISCONNECTED\nMODEM: state=S1_IDLE\nClients requesting connection: (none)'
RUNTIME = 'System_state: S4_RUNNING\nStart_time: 2026-11-06 08:00:00\nRuntime_sec: 90'


def health(pid="553", start="1000", boot=BOOT):
    return f'boot_id={boot}\nhostname=30001189\nMainPID={pid}\nExecMainStartTimestampMonotonic={start}\nActiveState=active'


def fixture():
    meter = SimpleNamespace(host="192.0.2.1", hostname="30001189", presses=[],
                            setup_custom_display=Mock(), force_diagnostics=Mock(), set_brightness=Mock(), cli=Mock(), get_info=Mock())
    meter.press = lambda key: meter.presses.append(key)
    session = MeterSession(meter)
    meter.session = session
    session.admitted = True
    supervisor = MeterSupervisor(session)
    supervisor._log = Mock()
    shared = SharedState()
    shared.last_error = None
    shared.current_program = "cycle_all"
    shared.meter_session = session
    return meter, session, supervisor, shared


class MeterLifecycleTests(unittest.TestCase):
    def test_incomplete_systemd_sample_is_not_a_generation_change(self):
        meter, session, supervisor, _ = fixture()
        session.generation = (BOOT, '553', '1000')
        meter._firmwares = {'KEY_PAD_2': '1'}
        session.mark_ready()
        partial = f'boot_id={BOOT}\nhostname=30001189'
        supervisor.observe(partial, RUNTIME, IDLE, DIAGS)
        supervisor.observe(health(), RUNTIME, IDLE, DIAGS)
        self.assertEqual(session.generation, (BOOT, '553', '1000'))
        self.assertEqual(session.epoch, 0)
        self.assertTrue(session.ready)
        self.assertEqual(meter._firmwares, {'KEY_PAD_2': '1'})

    def test_health_read_immediately_retries_missing_fields(self):
        _, session, supervisor, _ = fixture()
        partial = f'boot_id={BOOT}\nhostname=30001189'
        complete = health() + '\n__health_end__\n'
        supervisor._command = Mock(side_effect=[partial, complete])
        self.assertEqual(supervisor._read_health(Mock()), complete)
        self.assertEqual(supervisor._command.call_count, 2)
        supervisor._command = Mock(return_value=partial)
        with self.assertRaisesRegex(RuntimeError, 'Incomplete meter health'):
            supervisor._read_health(Mock())
        self.assertEqual(supervisor._command.call_count, 2)

    def test_one_blank_raw_ui_sample_is_reread_before_interrupting(self):
        _, session, supervisor, _ = fixture()
        supervisor._command = Mock(side_effect=['', HOME])
        session.mark_ready()
        with patch.object(session.stopped, 'wait'):
            self.assertEqual(supervisor._read_raw_ui(Mock()), HOME)
        self.assertEqual(supervisor._command.call_count, 2)
        self.assertTrue(session.ready)
        self.assertEqual(session.epoch, 0)

    def test_retry_reuses_inventory_already_read_by_recovery(self):
        meter, session, _, shared = fixture()
        session.generation = (BOOT, '553', '1000')
        session.mark_ready()
        attempts = []
        def run():
            attempts.append(1)
            if len(attempts) == 1:
                session.interrupt('Temporary UI loss')
                session.mark_ready()
                raise MeterInterrupted('Temporary UI loss')
        run_subtest(meter, shared, 'screen test', run)
        self.assertEqual(len(attempts), 2)
        meter.get_info.assert_called_once_with()

    def test_command_readers_wait_for_eof_after_early_exit_status(self):
        from lib.meter.ssh_meter import SSHMeter
        _, session, supervisor, _ = fixture()

        class Channel:
            eof_received = False
            closed = False
            pending = b'first'
            def recv_ready(self): return bool(self.pending)
            def recv_stderr_ready(self): return False
            def exit_status_ready(self): return True
            def recv_exit_status(self): return 0
            def recv(self, count):
                chunk, self.pending = self.pending, b''
                return chunk
            def deliver_tail(self, *args):
                self.pending, self.eof_received = b'second', True
            def close(self): self.closed = True

        channel = Channel()
        client = Mock()
        client.exec_command.return_value = (None, SimpleNamespace(channel=channel), None)
        with patch.object(session.stopped, 'wait', side_effect=channel.deliver_tail):
            self.assertEqual(supervisor._command(client, 'read'), 'firstsecond')
        channel = Channel()
        with patch('lib.meter.ssh_meter.time.sleep', side_effect=channel.deliver_tail):
            self.assertEqual(SSHMeter._read_command_result(SimpleNamespace(channel=channel), None),
                             (0, 'firstsecond', ''))

    def test_active_app_moves_from_restart_to_booting_with_minimum_wait(self):
        _, session, supervisor, _ = fixture()
        session.interrupt('Service stopped', phase='restarting')
        now = [100.0]
        with patch('lib.meter.supervisor.time.monotonic', side_effect=lambda: now[0]):
            supervisor.observe(health(), RUNTIME.replace('90', '20'), IDLE, DIAGS)
            snapshot = session.snapshot()
            self.assertEqual(snapshot['phase'], 'booting')
            self.assertEqual(snapshot['runtime_sec'], 20)
            self.assertEqual(snapshot['startup_remaining_s'], 55)
            self.assertFalse(snapshot['ready'])
            now[0] = 155
            supervisor.observe(health(), RUNTIME, IDLE, DIAGS)
            self.assertEqual(session.phase, 'settling')
            self.assertEqual(session.stable_remaining_s, 3)
            for stamp in (159, 160):
                now[0] = stamp
                supervisor.observe(health(), RUNTIME, IDLE, DIAGS)
            self.assertTrue(session.ready)
            self.assertIsNone(session.snapshot()['startup_remaining_s'])

    def test_physical_pose_is_reacquired_after_disruption_between_subtests(self):
        from importlib import import_module
        physical = import_module('lib.automation.tests.physical_cycle_all')
        meter, session, _, shared = fixture()
        meter.set_ui_mode = Mock()
        meter.in_diagnostics = Mock(return_value=True)
        session.mark_ready()
        used_poses = []

        def stage(meter, shared, **kwargs):
            used_poses.append(kwargs['charuco_frame'])

        original_log = shared.log
        completed = []

        def record_stage(message, **options):
            original_log(message, **options)
            if message == 'Subtest complete':
                completed.append(shared.current_device)
                if len(completed) == 1:
                    session.interrupt('Update between physical stages')
                    session.mark_ready()

        shared.log = record_stage
        stages = [('first', stage, {}), ('second', stage, {})]
        with patch.object(physical, 'PHYSICAL_DEVICES', stages), \
             patch.object(physical, '_combined_solar_keypad_enabled', return_value=False), \
             patch.object(physical, 'RobotClient'), \
             patch.object(physical, 'run_and_retrieve_charuco', side_effect=['old pose', 'fresh pose']) as locate:
            physical.physical_cycle_all(meter, shared, first={'job_count': 1},
                                        second={'job_count': 1}, numBurnDelay=0)
        self.assertEqual(used_poses, ['old pose', 'fresh pose'])
        self.assertEqual(locate.call_count, 2)
        self.assertEqual(shared.device_results, {'first': 'pass', 'second': 'pass'})

    def test_late_markers_only(self):
        for message in ('WRITE_CONFIG_ITEM updating:PoleConfig', 'Rsync Started',
                        'DISPLAY_STRING:Configs', 'Clients that need to be awake: SELF',
                        'SAGENT RECV: {"command":"platformSleepResponse"}'):
            self.assertIsNone(transition_reason(message), message)
        self.assertEqual(transition_reason('PowerServer:sHandleTimerEvent: Grace period timeout')[0], 'sleep')
        self.assertEqual(transition_reason('SAGENT SEND: {"command":"platformSleep"}')[0], 'sleep')
        self.assertEqual(transition_reason('Updater:UpdaterCheckForUpdates: Installing legacy config')[0], 'updating')

    def test_restart_stale_diags_never_cause_toggle_presses(self):
        meter, session, supervisor, _ = fixture()
        now = [100.0]
        with patch('lib.meter.supervisor.time.monotonic', side_effect=lambda: now[0]):
            for stamp in (100, 104, 105):
                now[0] = stamp
                supervisor.observe(health(), RUNTIME, IDLE, DIAGS)
            self.assertTrue(session.ready)
            session.interrupt('MS3 update')
            now[0] = 110
            supervisor.observe(health('777', '2000'), RUNTIME, IDLE, DIAGS)
            now[0] = 200
            supervisor.observe(health('777', '2000'), RUNTIME, IDLE, DIAGS)
            self.assertFalse(session.ready)
            self.assertEqual(meter.presses, [])
            supervisor.observe(health('777', '2000'), RUNTIME, IDLE, HOME)
            self.assertEqual(meter.presses, ['diagnostics'])
            supervisor.journal_record({'MESSAGE': 'Diagnostics:DiagnosticsEnter: ENTER DIAGS',
                                       '_BOOT_ID': BOOT, '__MONOTONIC_TIMESTAMP': '2500'})
            for stamp in (201, 205, 206):
                now[0] = stamp
                supervisor.observe(health('777', '2000'), RUNTIME, IDLE, DIAGS)
            self.assertTrue(session.ready)

    def test_supervisor_needs_job_handoff_before_pressing(self):
        meter, session, supervisor, _ = fixture()
        session.mark_ready()
        self.assertTrue(session.claim('job'))
        supervisor.observe(health(), RUNTIME, IDLE, HOME)
        self.assertEqual(meter.presses, [])
        session.interrupt('update')
        supervisor.observe(health(), RUNTIME, IDLE, HOME)
        self.assertEqual(meter.presses, [])
        session.recovery_allowed = True
        supervisor.observe(health(), RUNTIME, IDLE, HOME)
        self.assertEqual(meter.presses, ['diagnostics'])

    def test_epoch_is_latched_after_fast_recovery_and_stop_on_fail_cannot_clear_it(self):
        _, session, _, shared = fixture()
        session.mark_ready()
        shared.attempt_epoch = session.epoch
        session.shared = shared
        session.interrupt('sleep')
        session.mark_ready()
        with self.assertRaises(MeterInterrupted):
            check_stop_event(shared)
        self.assertFalse(shared.continue_after_failure(False))

    def test_only_interrupted_subtest_is_restarted_with_fresh_results(self):
        meter, session, _, shared = fixture()
        session.mark_ready()
        shared.device_results['previous'] = 'pass'
        calls = []

        def subtest():
            calls.append(shared.attempt_epoch)
            if len(calls) == 1:
                shared.device_results['keypad'] = 'fail'
                session.interrupt('update')
                session.mark_ready()
                raise RuntimeError('legacy test wrapped the original exception')
            self.assertNotIn('keypad', shared.device_results)
            shared.device_results['keypad'] = 'pass'

        run_subtest(meter, shared, 'keypad', subtest)
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(*calls)
        self.assertEqual(shared.device_results, {'previous': 'pass', 'keypad': 'pass'})
        self.assertEqual(len(shared.extras['meter_interruptions']), 1)

    def test_call_in_observer_waits_without_retriggering(self):
        meter, session, _, shared = fixture()
        session.mark_ready()
        calls = []

        def call_in():
            calls.append('plus')
            shared.lifecycle_observer = True
            shared.extras['call_in_in_flight'] = True
            session.interrupt('expected call-in update')
            # A normal checkpoint during observation must preserve the function.
            check_stop_event(shared)
            session.mark_ready()
            shared.extras.pop('call_in_in_flight')

        run_subtest(meter, shared, 'call in', call_in)
        self.assertEqual(calls, ['plus'])

    def test_cancellation_breaks_recovery_wait(self):
        _, session, _, shared = fixture()
        shared.abort_event.set()
        with self.assertRaises(StopAutomation):
            session.wait_ready(shared)
        self.assertFalse(session.recovery_allowed)

    def test_bounded_retries_do_not_become_peripheral_failures(self):
        meter, session, _, shared = fixture()
        session.mark_ready()

        def interrupted():
            session.interrupt('repeated update')
            session.mark_ready()
            raise MeterInterrupted('update')

        with self.assertRaises(RecoveryFailed):
            run_subtest(meter, shared, 'keypad', interrupted, max_restarts=1)
        self.assertEqual(len(shared.extras['meter_interruptions']), 2)
        self.assertNotIn('keypad', shared.device_results)

    def test_sleep_invalidates_pre_sleep_diagnostics_proof_without_a_new_process(self):
        meter, session, supervisor, _ = fixture()
        session.generation = (BOOT, '553', '1000')
        supervisor.diag_records = [(BOOT, 2000)]
        session.mark_ready()
        supervisor.journal_record({'MESSAGE': 'PowerServer:sHandleTimerEvent: Grace period timeout',
                                   '_BOOT_ID': BOOT, '__MONOTONIC_TIMESTAMP': '3000'})
        supervisor.observe(health(), RUNTIME, IDLE, DIAGS)
        self.assertFalse(session.ready)
        self.assertEqual(meter.presses, [])
        self.assertIsNone(supervisor.idle_since)

    def test_linux_reboot_rejects_old_boot_diagnostics_proof(self):
        _, session, supervisor, _ = fixture()
        session.generation = (BOOT, '553', '1000')
        supervisor.diag_records = [(BOOT, 2000)]
        session.mark_ready()
        supervisor.observe(health(boot='a8cad31e-b154-4867-9e53-9eadbe5b0c8f'), RUNTIME, IDLE, DIAGS)
        self.assertFalse(session.ready)
        self.assertEqual(session.snapshot()['last_interruption'], 'Linux reboot')
        self.assertIn('diagnostics-entry journal evidence', session.reason)

    def test_notice_without_update_is_not_classified_as_restart(self):
        from lib.meter.supervisor import page_kind
        self.assertEqual(page_kind('<html><title>Notice</title>Payment declined</html>'), 'other')
        self.assertEqual(page_kind('<html><title>Notice</title>This meter is being updated</html>'), 'transition')

    def test_new_daily_log_does_not_delete_older_or_legacy_logs(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old_day = root / '2026-01-01'
            old_day.mkdir()
            old_job = old_day / 'old_cycle_all.log'
            old_job.write_text('keep old job', encoding='utf-8')
            legacy = root / 'meters' / '30001189_192.0.2.1'
            legacy.mkdir(parents=True)
            old_journal = legacy / 'journal.ndjson'
            old_journal.write_text('keep old journal', encoding='utf-8')
            os.utime(old_job, (0, 0))
            os.utime(old_journal, (0, 0))
            _, _, supervisor, _ = fixture()
            with patch('lib.meter.supervisor.LOG_ROOT', root):
                supervisor.write_line('new session')
                path = Path(supervisor.log_path)
                supervisor.close()
            self.assertRegex(path.parent.name, r'^\d{4}-\d{2}-\d{2}$')
            self.assertEqual(path.parent.parent, root)
            self.assertRegex(path.name, r'^\d{2}-\d{2}-\d{2}_30001189\.log$')
            self.assertTrue(old_job.exists())
            self.assertTrue(old_journal.exists())

    def test_runtime_alone_does_not_spam_lifecycle_logs_but_gate_changes_publish(self):
        meter, session, supervisor, _ = fixture()
        meter.public_info = Mock(return_value={})
        session.mark_ready()
        with patch('lib.sse.sse_queue_manager.SSEQM.broadcast') as broadcast, patch('builtins.print') as console:
            session.runtime_sec = 100
            supervisor._publish()
            session.runtime_sec = 101
            supervisor._publish()
            self.assertEqual(supervisor._log.call_count, 1)
            self.assertEqual(broadcast.call_count, 1)
            session.interrupt('Applying update', phase='updating')
            supervisor._publish()
            self.assertEqual(broadcast.call_count, 2)
            self.assertIn('ready -> updating', str(console.call_args))

    def test_recovery_replays_results_before_releasing_readiness(self):
        meter, session, supervisor, _ = fixture()
        session.generation = (BOOT, '553', '1000')
        payload = {'overall_result': 'PASS', 'physical': {'keypad': 'pass'}}
        session.set_desired(mode='results', results=payload, banner='', brightness=15)
        revision = session.display_revision
        supervisor._restore_display()
        meter.setup_custom_display.assert_called_once()
        self.assertTrue(any('results.json' in str(call.args[0]) for call in meter.cli.call_args_list))
        meter.set_brightness.assert_called_once_with(15)
        self.assertEqual(session.display_revision, revision)
        self.assertEqual(session.desired['results'], payload)
        self.assertFalse(session.ready)

    def test_command_exit_wait_has_an_overall_deadline(self):
        from lib.meter.ssh_meter import SSHMeter
        channel = Mock()
        channel.recv_ready.return_value = False
        channel.recv_stderr_ready.return_value = False
        channel.exit_status_ready.return_value = False
        with patch('lib.meter.ssh_meter.time.monotonic', side_effect=[0, 1, 2, 3]), \
             patch('lib.meter.ssh_meter.time.sleep'):
            with self.assertRaises(TimeoutError):
                SSHMeter._read_command_result(SimpleNamespace(channel=channel), None, timeout=2)
        channel.close.assert_called_once()

    def test_history_does_not_reapply_old_interruptions(self):
        _, session, supervisor, _ = fixture()
        session.mark_ready()
        supervisor.journal_record({'MESSAGE': 'PowerServer:sHandleTimerEvent: Grace period timeout'}, history=True)
        self.assertTrue(session.ready)
        self.assertEqual(session.epoch, 0)

    def test_journal_reconnect_resumes_cursor_and_logs_history_once(self):
        meter, session, supervisor, _ = fixture()
        session.mark_ready()
        commands, records = [], []

        class Stop:
            flag = False
            def is_set(self): return self.flag
            def set(self): self.flag = True
            def wait(self, seconds): return self.flag

        session.stopped = Stop()

        class Channel:
            def __init__(self, cursor):
                self.payload = (json.dumps({'__CURSOR': cursor, 'MESSAGE': 'new record'}) + '\n').encode()
            def recv_ready(self): return bool(self.payload)
            def recv(self, count):
                data, self.payload = self.payload, b''
                return data
            def exit_status_ready(self): return not self.payload
            def recv_exit_status(self): return 0
            def close(self): pass

        class Client:
            def __init__(self, cursor): self.channel = Channel(cursor)
            def exec_command(self, command, timeout):
                commands.append(command)
                return None, SimpleNamespace(channel=self.channel), SimpleNamespace(read=lambda: b'')
            def close(self): pass

        clients = iter([Client('c1'), Client('c2')])
        supervisor._connect = lambda: next(clients)
        supervisor._command = lambda client, command, timeout: json.dumps(
            {'__CURSOR': 'c0' if client.channel.payload.find(b'c1') >= 0 else 'c1', 'MESSAGE': 'history'})
        original = supervisor.journal_record
        def record(row, **kwargs):
            records.append(row['__CURSOR'])
            original(row, **kwargs)
            if row['__CURSOR'] == 'c2': session.stopped.set()
        supervisor.journal_record = record
        supervisor._journal()
        self.assertIn('--after-cursor=c0', commands[0])
        self.assertIn('--after-cursor=c1', commands[1])
        self.assertEqual(records, ['c0', 'c1', 'c2'])
        self.assertTrue(session.ready)
        events = [call.args[0] for call in supervisor._log.call_args_list]
        self.assertEqual(events.count('journal_history_start'), 1)
        self.assertEqual(events.count('journal_history_end'), 1)
        self.assertEqual(events.count('journal_stream_started'), 2)

    def test_external_controls_cannot_enter_a_job_lease(self):
        _, session, _, _ = fixture()
        session.mark_ready()
        self.assertTrue(session.claim('job'))
        with self.assertRaises(MeterInterrupted):
            with session.control(): pass
        with session.bind('job'):
            with session.control(): session.action_checkpoint()

    def test_real_sleep_capture_has_live_grace_and_backfilled_sleep(self):
        path = Path(__file__).resolve().parents[1] / 'wc_copy/test/ms3_full_background_monitor/captures/192.168.69.138_20261106_081107_761121/journal.ndjson'
        if not path.exists():
            self.skipTest('investigation capture is not installed')
        _, session, supervisor, _ = fixture()
        session.mark_ready()
        grace = sleeping = None
        for line in path.read_text(encoding='utf-8').splitlines():
            row = json.loads(line)
            record = row['journal']
            if 'Grace period timeout' in str(record.get('MESSAGE', '')):
                grace = row['elapsed_s']
                supervisor.journal_record(record)
                self.assertFalse(session.ready)
                self.assertEqual(session.phase, 'sleep')
            if str(record.get('MESSAGE', '')).endswith('PSSetNeedsPowerNow: Sleeping'):
                sleeping = row['elapsed_s']
        self.assertLess(grace, 225)
        self.assertGreater(sleeping, 275)


if __name__ == '__main__':
    unittest.main()
