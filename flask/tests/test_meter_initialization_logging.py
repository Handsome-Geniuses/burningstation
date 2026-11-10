"""Admission and lifetime log regressions; no meter, robot, or DB connections."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from lib.automation.shared_state import SharedState
from lib.meter.lifecycle import MeterSession, MeterInterrupted
from lib.meter.ssh_meter import SSHMeter
from lib.meter.supervisor import MeterSupervisor
from lib.store import store


def module_page(name, version, identifier):
    return (f'<html><div class="diagTitle">Service:IPSBus Modules</div><pre>Modules\n'
            f'---------------------\n{name}\nModule FW: {version} | Mod Func: 61 | Full ID: {identifier}\n'
            'Press 2 for next module\n</pre></html>')


def overview_page(modules, selected=None):
    """Use the real overview layout: type/function/FW columns before details."""
    header = 'Module                    FW Version  uptime(sec)   Last Message(elapsed)\n'
    rows = '\n'.join(f'{name} 89 89 {version} 720 0' for name, version, _ in modules)
    if selected is None and modules:
        selected = modules[0]
    if selected is None:
        return '<html><div class="diagTitle">Service:IPSBus Modules</div><pre>' + header + '\n---------------------\n</pre></html>'
    return module_page(*selected).replace('Modules\n', header + rows + '\n', 1)


class OfflineMeter(SSHMeter):
    @property
    def hostname(self):
        return '30001189'


def inventory_meter(pages=None):
    meter = OfflineMeter('192.0.2.1')
    meter.cli = Mock(return_value='1024x768')
    meter.press = Mock()
    meter.goto_diagnostics_path = Mock()
    meter.get_meter_region = Mock(return_value='us')
    meter.get_system_versions = Mock(return_value={'system_version': '48794', 'system_sub_version': '4'})
    first = module_page('PRINTER', 207, 1234)
    meter._get_uipage_html = Mock(side_effect=pages or [first, module_page('COIN_SHUTTER', 545, 5678), first])
    session = MeterSession(meter)
    meter.session = session
    session.mark_ready()
    session.owner = 'admission'
    return meter, session


class MeterInitializationTests(unittest.TestCase):
    def test_blank_rendered_ui_retries_but_update_notices_block_immediately(self):
        meter, session = inventory_meter()
        del meter._get_uipage_html
        page = '<html><div class="diagTitle">Service</div></html>'
        meter._http_request = Mock(side_effect=[SimpleNamespace(text=''), SimpleNamespace(text=page)])
        with session.bind('admission'), patch('lib.meter.ssh_meter.time.sleep'):
            self.assertEqual(meter.get_ui_page_html(), page)
        self.assertTrue(session.ready)
        self.assertEqual(session.epoch, 0)
        meter._http_request = Mock(return_value=SimpleNamespace(text='<html>This meter is being updated</html>'))
        with session.bind('admission'):
            with self.assertRaises(MeterInterrupted):
                meter.get_ui_page_html()
        self.assertEqual(meter._http_request.call_count, 1)

    def test_single_keypad_inventory_needs_no_printer_or_other_optional_modules(self):
        page = overview_page([('KEY_PAD_2', 1, 1234)])
        meter, session = inventory_meter([page])
        with session.bind('admission'):
            info = meter.get_info(force=True)
        self.assertEqual(set(info['module_info']), {'KEY_PAD_2'})
        self.assertNotIn('PRINTER', info['firmwares'])
        meter.press.assert_not_called()  # No need to advance a one-module overview.

    def test_valid_empty_overview_is_an_inventory_not_a_failed_read(self):
        meter, session = inventory_meter([overview_page([])])
        with session.bind('admission'):
            info = meter.get_info(force=True)
        self.assertEqual(info['module_info'], {})
        self.assertEqual(info['firmwares'], {})
        self.assertEqual(meter._module_details_cache, {})

    def test_restart_recovery_can_read_inventory_and_restore_before_becoming_ready(self):
        meter, session = inventory_meter()
        session.owner = None
        session.admitted = True
        session.interrupt('MS3 generation changed', new_generation=True)
        session.generation = ('boot', '200', '1000')
        supervisor = MeterSupervisor(session)
        session.supervisor = supervisor
        supervisor._log = Mock()
        meter.force_diagnostics = Mock()
        session.set_desired(mode='results', results={'overall_result': 'PASS'}, brightness=15)
        with patch('lib.meter.ssh_meter.time.sleep'), \
             patch('lib.meter.ssh_meter.is_custom_display_current', return_value=False), \
             patch('lib.meter.ssh_meter.write_ui_page') as write_ui, \
             patch('lib.meter.ssh_meter.write_ui_overlay'), \
             patch('lib.meter.ssh_meter.upload_image'):
            supervisor._restore_display()
        write_ui.assert_called_once_with(meter)
        self.assertFalse(session.ready)
        self.assertEqual(session.display_applied, (session.generation, session.display_revision))
        self.assertIn('PRINTER', meter._module_info_cache)
        health = 'boot_id=boot\nhostname=30001189\nMainPID=200\nExecMainStartTimestampMonotonic=1000\nActiveState=active'
        runtime = 'System_state: S4_RUNNING\nRuntime_sec: 150'
        status = 'CIM: state=S1_WAITING_FOR_CALL_TIME\nClients requesting connection: (none)'
        with patch('lib.meter.supervisor.time.monotonic', return_value=100) as clock:
            supervisor.observe(health, runtime, status, '<html><div class="diagTitle">Service</div></html>')
            self.assertFalse(session.ready)
            clock.return_value = 104
            supervisor.observe(health, runtime, status, '<html><div class="diagTitle">Service</div></html>')
        self.assertTrue(session.ready)

    def test_real_inventory_enumerates_before_public_readiness_and_drives_meter_type(self):
        meter, session = inventory_meter()
        self.assertEqual(meter.status, 'initializing')
        self.assertFalse(session.snapshot()['ready'])
        with session.bind('admission'), patch('lib.meter.ssh_meter.time.sleep'):
            info = meter.get_info(force=True)
        self.assertEqual(info['firmwares'], {'PRINTER': '207', 'COIN_SHUTTER': '545'})
        self.assertEqual(info['module_info']['PRINTER'], {'ver': 207, 'mod': 61, 'id': 1234})
        self.assertEqual(info['meter_type'], 'ms3')
        self.assertEqual([call.args[0] for call in meter.goto_diagnostics_path.call_args_list], [['IPSBus Modules'], []])

    def test_parse_failure_never_commits_partial_inventory(self):
        meter, session = inventory_meter([module_page('PRINTER', 207, 1234), '<html>not a module page</html>'])
        with session.bind('admission'), patch('lib.meter.ssh_meter.time.sleep'):
            with self.assertRaisesRegex(ValueError, 'Divider not found'):
                meter.get_info(force=True)
        self.assertIsNone(meter._firmwares)
        self.assertIsNone(meter._module_info_cache)
        self.assertIsNone(meter._module_details_cache)
        self.assertFalse(session.admitted)

    def test_fast_restart_during_enumeration_never_commits_old_generation(self):
        meter, session = inventory_meter()
        def navigate(path):
            if not path:
                session.interrupt('Restart before inventory commit')
                session.mark_ready()
        meter.goto_diagnostics_path.side_effect = navigate
        with session.bind('admission'), patch('lib.meter.ssh_meter.time.sleep'):
            with self.assertRaises(MeterInterrupted):
                meter.get_info(force=True)
        self.assertIsNone(meter._module_details_cache)

    def test_retry_uses_existing_inventory_cache_without_another_module_walk(self):
        from lib.automation.recovery import run_subtest
        meter, session = inventory_meter([overview_page([('KEY_PAD_2', 1, 1234)])])
        with session.bind('admission'):
            meter.get_info(force=True)
        session.owner = 'job'
        session.admitted = True
        shared = SharedState()
        shared.control_owner = 'job'
        shared.last_error = None
        attempts = []
        def run():
            attempts.append(1)
            if len(attempts) == 1:
                session.interrupt('Temporary page loss')
                session.mark_ready()
                raise MeterInterrupted('Temporary page loss')
        with session.bind('job'):
            run_subtest(meter, shared, 'keypad', run)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(meter._get_uipage_html.call_count, 1)
        self.assertEqual(meter._module_info_cache['KEY_PAD_2']['ver'], 1)

    def test_low_level_results_writer_keeps_its_original_unconditional_behavior(self):
        from lib.meter.display_utils import write_results_json
        meter, session = inventory_meter()
        session.interrupt('Application restarting')
        write_results_json(meter, {'overall_result': 'PASS'})
        self.assertEqual(meter.cli.call_count, 2)
        self.assertIn('results.json', meter.cli.call_args.args[0])
        self.assertIsNone(session.desired['results'])

    def test_high_level_results_are_remembered_without_waiting_for_an_unavailable_meter(self):
        meter, session = inventory_meter()
        session.interrupt('Application restarting')
        session.wait_ready = Mock(side_effect=AssertionError('Result rendering must not wait'))
        meter._apply_display_results({'overall_result': 'PASS'})
        meter.cli.assert_not_called()
        self.assertEqual(session.desired['results'], {'overall_result': 'PASS'})
        self.assertEqual(session.desired['mode'], 'results')

    def test_auto_display_upload_finishes_before_public_readiness(self):
        from lib.meter.meter_manager import METERMANAGER as manager
        meter, session = inventory_meter([overview_page([])])
        session.owner = None
        stages = []
        def setup():
            self.assertEqual(session.owner, 'admission')
            self.assertFalse(session.admitted)
            self.assertFalse(session.snapshot()['ready'])
            stages.append('display')
        meter.setup_custom_display = Mock(side_effect=setup)
        with patch.object(manager, 'meters', {meter.host: meter}), \
             patch.object(manager, '_METERMANAGER__newly_ready', set()), \
             patch.object(manager, '_METERMANAGER__attempts', {}), \
             patch.object(manager, '_METERMANAGER__inflight', set()), \
             patch('lib.meter.meter_manager.insert_sshmeter', return_value=(42,)), \
             patch('lib.meter.meter_manager.SSEQM.broadcast'), \
             patch.dict('lib.meter.meter_manager.states', {'workOrder': None, 'mode': 'auto'}):
            manager._METERMANAGER__admit(meter.host, meter, session)
        self.assertEqual(stages, ['display'])
        self.assertTrue(session.admitted)
        self.assertTrue(session.snapshot()['ready'])

    def test_work_order_failure_does_not_reject_a_valid_meter(self):
        from lib.meter.meter_manager import METERMANAGER as manager
        meter, session = inventory_meter([overview_page([])])
        session.owner = None
        with patch.object(manager, 'meters', {meter.host: meter}), \
             patch.object(manager, '_METERMANAGER__newly_ready', set()), \
             patch.object(manager, '_METERMANAGER__attempts', {}), \
             patch.object(manager, '_METERMANAGER__inflight', set()), \
             patch('lib.meter.meter_manager.insert_sshmeter', return_value=(42,)), \
             patch('lib.meter.meter_manager.update_meter_work_order', side_effect=RuntimeError('DB association failed')), \
             patch('lib.meter.meter_manager.SSEQM.broadcast') as broadcast, \
             patch.dict('lib.meter.meter_manager.states', {'workOrder': 17}):
            manager._METERMANAGER__admit(meter.host, meter, session)
        self.assertTrue(session.admitted)
        self.assertTrue(session.ready)
        self.assertTrue(any(c.args[0] == 'notify' for c in broadcast.call_args_list))

    def test_refresh_schedules_one_admission_only_after_startup_readiness(self):
        from lib.meter.meter_manager import METERMANAGER as manager
        meter, session = inventory_meter([overview_page([])])
        meter.close_if_idle = Mock()
        session.owner = None
        session.ready = False
        workers = Mock()
        with patch.object(manager, 'meters', {meter.host: meter}), \
             patch.object(manager, '_METERMANAGER__meters', {meter.host}), \
             patch.object(manager, '_METERMANAGER__newly_ready', set()), \
             patch.object(manager, '_METERMANAGER__reachable', set()), \
             patch.object(manager, '_METERMANAGER__attempts', {}), \
             patch.object(manager, '_METERMANAGER__retry_at', {}), \
             patch.object(manager, '_METERMANAGER__stale_counts', {}), \
             patch.object(manager, '_METERMANAGER__inflight', set()), \
             patch.object(manager, '_METERMANAGER__workers', workers), \
             patch('ip_scanner.get_ips', return_value=[meter.host]), \
             patch('lib.meter.meter_manager.insert_sshmeter', return_value=(42,)), \
             patch('lib.meter.meter_manager.SSEQM.broadcast'), \
             patch.dict('lib.meter.meter_manager.states', {'workOrder': None}):
            self.assertEqual(manager.refresh()[0], set())
            workers.submit.assert_not_called()
            session.mark_ready()
            self.assertEqual(manager.refresh()[0], set())
            manager.refresh()
            self.assertEqual(workers.submit.call_count, 1)
            self.assertFalse(session.snapshot()['ready'])
            task, ip, captured_meter, captured_session = workers.submit.call_args.args
            task(ip, captured_meter, captured_session)
            self.assertEqual(manager.refresh()[0], {meter.host})
            self.assertTrue(session.snapshot()['ready'])

    def test_failed_supervisor_startup_does_not_strand_a_registered_meter(self):
        from lib.meter.meter_manager import METERMANAGER as manager
        meter, _ = inventory_meter()
        meter.connect = Mock()
        meter.close = Mock()
        with patch.object(manager, 'MeterClass', return_value=meter), \
             patch.object(manager, 'meters', {}), patch.object(manager, '_METERMANAGER__meters', set()), \
             patch.object(manager, '_METERMANAGER__reachable', {meter.host}), \
             patch.object(manager, '_METERMANAGER__inflight', {meter.host}), \
             patch.object(manager, '_METERMANAGER__attempts', {}), \
             patch.object(manager, '_METERMANAGER__retry_at', {}), \
             patch('lib.meter.meter_manager.MeterSupervisor') as supervisor, \
             patch('lib.meter.meter_manager.SSEQM.broadcast'):
            supervisor.return_value.start.side_effect = RuntimeError('Supervisor startup failed')
            manager._METERMANAGER__identify(meter.host)
            self.assertNotIn(meter.host, manager.meters)
            self.assertNotIn(meter.host, manager._METERMANAGER__meters)
            self.assertNotIn(meter.host, manager._METERMANAGER__inflight)
            self.assertIn(meter.host, manager._METERMANAGER__retry_at)
        meter.close.assert_called()

    def test_manager_admits_after_real_inventory_and_caches_it_for_jobs(self):
        meter, session = inventory_meter()
        self.admit(meter, session)
        self.assertIn('PRINTER', session.info['module_info'])

    def test_manager_admits_a_valid_inventory_with_no_peripherals(self):
        meter, session = inventory_meter([overview_page([])])
        self.admit(meter, session)
        self.assertEqual(session.info['module_info'], {})
        self.assertEqual(session.info['firmwares'], {})

    def admit(self, meter, session):
        from lib.meter.meter_manager import METERMANAGER as manager
        session.owner = None
        with patch.object(manager, 'meters', {meter.host: meter}), \
             patch.object(manager, '_METERMANAGER__newly_ready', set()), \
             patch.object(manager, '_METERMANAGER__attempts', {}), \
             patch('lib.meter.meter_manager.insert_sshmeter', return_value=(42,)) as insert, \
             patch('lib.meter.meter_manager.update_meter_work_order'), \
             patch('lib.meter.meter_manager.SSEQM.broadcast'), \
             patch.dict('lib.meter.meter_manager.states', {'workOrder': None}), \
             patch('lib.meter.ssh_meter.time.sleep'):
            manager._METERMANAGER__admit(meter.host, meter, session)
        self.assertTrue(session.admitted)
        self.assertTrue(session.snapshot()['ready'])
        self.assertEqual(meter.db_id, 42)
        insert.assert_called_once_with(meter)


class MeterLifetimeLogTests(unittest.TestCase):
    def supervisor(self):
        meter = SimpleNamespace(host='192.0.2.1', hostname='30001189')
        session = MeterSession(meter)
        meter.session = session
        supervisor = MeterSupervisor(session)
        session.supervisor = supervisor
        return supervisor

    def test_jobs_journal_ui_and_removal_share_one_file_without_duplicate_journal(self):
        with tempfile.TemporaryDirectory() as temporary, patch('lib.meter.supervisor.LOG_ROOT', Path(temporary)):
            supervisor = self.supervisor()
            supervisor._log('session_started')
            path = Path(supervisor.log_path)
            shared = SharedState()
            shared.set_session_log(supervisor)
            supervisor.session.subscribers.add(shared)
            supervisor._log('job_started', program='cycle_all')
            shared.log('first test payload', source='test.first')
            supervisor.journal_record({'MESSAGE': 'unique journal payload', '__CURSOR': 'c1', '_BOOT_ID': 'boot1'})
            supervisor.record_ui(source='ssh:UI_0.html', html='<html>Changed page</html>')
            supervisor.record_ui(source='ssh:UI_0.html', error='No such file')
            supervisor._log('job_finalized', program='cycle_all', result='pass')
            shared.flush_logs()
            supervisor._log('job_started', program='operator_keypad')
            shared.log('second test payload', source='test.second')
            supervisor.close()
            text = path.read_text(encoding='utf-8')
            self.assertIn('RUNNING CYCLE_ALL', text)
            self.assertIn('RUNNING OPERATOR_KEYPAD', text)
            self.assertIn('test.first: first test payload', text)
            self.assertIn('test.second: second test payload', text)
            self.assertNotIn('listener.py.run:', text)
            self.assertEqual(text.count('unique journal payload'), 1)
            self.assertIn('"boot_id": "boot1"', text)
            self.assertIn('<html>Changed page</html>', text)
            self.assertIn('No such file', text)
            self.assertIn('METER REMOVED', text)
            self.assertTrue(any('unique journal payload' in line for line in shared.logs))
            self.assertEqual(list(Path(temporary).rglob('*.log')), [path])

    def test_journal_lines_keep_timing_and_cursor_without_repeated_service_fields(self):
        with tempfile.TemporaryDirectory() as temporary, patch('lib.meter.supervisor.LOG_ROOT', Path(temporary)):
            supervisor = self.supervisor()
            record = {'MESSAGE': 'Readable journal event', '__REALTIME_TIMESTAMP': '123456789',
                      '__MONOTONIC_TIMESTAMP': '98765', '__CURSOR': 'cursor-1',
                      '_BOOT_ID': 'boot-1', '_PID': '42',
                      '_SYSTEMD_INVOCATION_ID': 'invocation-1',
                      '_SYSTEMD_UNIT': 'MS3_Platform.service', '_CMDLINE': 'repeated command line'}
            supervisor.journal_record(record, history=True)
            supervisor.journal_record({**record, 'MESSAGE': 'Another event', '__CURSOR': 'cursor-2'})
            supervisor.journal_record({**record, 'MESSAGE': 'Modem event', '__CURSOR': 'cursor-3',
                                       '_SYSTEMD_UNIT': 'MS3_Modem.service'})
            supervisor.close()
            text = Path(supervisor.log_path).read_text(encoding='utf-8')
            lines = [line for line in text.splitlines() if ' supervisor.journal: ' in line]
            self.assertEqual(len(lines), 3)
            self.assertIn('supervisor.journal: Readable journal event | {', lines[0])
            self.assertIn('"__REALTIME_TIMESTAMP":"123456789"', lines[0])
            self.assertIn('"__MONOTONIC_TIMESTAMP":"98765"', lines[0])
            self.assertIn('"__CURSOR":"cursor-1"', lines[0])
            self.assertNotIn('_SYSTEMD_UNIT', lines[0])
            self.assertIn('"_SYSTEMD_UNIT":"MS3_Modem.service"', lines[2])
            self.assertNotIn('_CMDLINE', text)
            self.assertEqual(text.count('supervisor.journal_source_changed:'), 2)
            self.assertEqual(text.count('"boot_id": "boot-1"'), 2)

    def test_card_read_payload_is_redacted_in_file_and_job_evidence(self):
        with tempfile.TemporaryDirectory() as temporary, patch('lib.meter.supervisor.LOG_ROOT', Path(temporary)):
            supervisor = self.supervisor()
            shared = SharedState()
            supervisor.session.subscribers.add(shared)
            supervisor.journal_record({'MESSAGE': 'CARD_READ_DATA secret-card-payload',
                                       '__CURSOR': 'cursor-4'})
            supervisor.close()
            text = Path(supervisor.log_path).read_text(encoding='utf-8')
            self.assertIn('CARD_READ_DATA [payload redacted]', text)
            self.assertNotIn('secret-card-payload', text)
            self.assertTrue(any('CARD_READ_DATA [payload redacted]' in line for line in shared.logs))
            self.assertFalse(any('secret-card-payload' in line for line in shared.logs))

    def test_lifecycle_writer_batches_until_flush(self):
        with tempfile.TemporaryDirectory() as temporary, patch('lib.meter.supervisor.LOG_ROOT', Path(temporary)):
            supervisor = self.supervisor()
            with patch.object(supervisor, 'last_flush', time.monotonic()):
                supervisor.write_line('first pending line')
                path = Path(supervisor.log_path)
                self.assertEqual(path.read_text(encoding='utf-8'), '')
                supervisor.write_line('second pending line')
                supervisor.flush_log()
                self.assertEqual(path.read_text(encoding='utf-8'),
                                 'first pending line\nsecond pending line\n')
            supervisor.close()

    def test_same_meter_redetection_gets_a_different_file(self):
        from datetime import datetime
        with tempfile.TemporaryDirectory() as temporary, \
             patch('lib.meter.supervisor.LOG_ROOT', Path(temporary)), \
             patch('lib.meter.supervisor.datetime') as clock:
            clock.now.return_value = datetime(2026, 11, 10, 13, 8, 54)
            first, second = self.supervisor(), self.supervisor()
            first._log('session_started')
            first.close()
            second._log('session_started')
            second.close()
            self.assertEqual(Path(first.log_path).name, '13-08-54_30001189.log')
            self.assertEqual(Path(second.log_path).name, '13-08-54_30001189_2.log')
            self.assertEqual(len(list(Path(temporary).rglob('*.log'))), 2)

    def test_managed_job_uses_supervisor_evidence_without_listener_or_monitor_dependencies(self):
        from lib.automation import runner
        import builtins
        original_import = builtins.__import__
        def import_without_legacy(name, *args, **kwargs):
            if name.startswith(('lib.automation.listener', 'lib.automation.monitors')):
                raise AssertionError('Retired listener imported')
            return original_import(name, *args, **kwargs)
        with tempfile.TemporaryDirectory() as temporary, patch('lib.meter.supervisor.LOG_ROOT', Path(temporary)):
            supervisor = self.supervisor()
            session, meter = supervisor.session, supervisor.meter
            meter.clear_banner_text = Mock()
            session.admitted = session.journal_connected = True
            session.mark_ready()
            supervisor._log('session_started')
            shared = SharedState()
            shared.last_error = None
            shared.current_program = 'offline'
            shared.set_session_log(supervisor)
            def run(meter, shared):
                supervisor.journal_record({'MESSAGE': 'single live record', '__REALTIME_TIMESTAMP': '1000000'})
                self.assertTrue(any('single live record' in line for line in shared.logs))
            with patch.dict(runner.PROGRAM_REGISTRY, {'offline': run}), \
                 patch('builtins.__import__', side_effect=import_without_legacy):
                runner.run_test_job(meter, 'offline', {'monitors': []}, shared)
            self.assertEqual(session.subscribers, set())
            supervisor.close()
            self.assertEqual(Path(supervisor.log_path).read_text().count('single live record'), 1)

    def test_job_entrypoint_uses_lifetime_writer_for_multiple_jobs_even_with_log_false(self):
        from lib.automation import jobs
        with tempfile.TemporaryDirectory() as temporary, patch('lib.meter.supervisor.LOG_ROOT', Path(temporary)):
            supervisor = self.supervisor()
            session, meter = supervisor.session, supervisor.meter
            meter.status, meter.results, meter.db_id = 'ready', {}, None
            meter.connect, meter.get_info = Mock(), Mock(return_value={})
            meter.beep, meter.public_info = Mock(), Mock(return_value={})
            session.admitted = session.journal_connected = True
            session.mark_ready()
            supervisor._log('session_started')

            def run(meter, name, kwargs, shared, **options):
                shared.log(f'payload for {name}', source='offline_job')

            with patch.dict(jobs.mm.meters, {meter.host: meter}, clear=True), \
                 patch.object(jobs, 'run_test_job', side_effect=run), \
                 patch.object(jobs, '_handle_auto_job_done'), patch.object(jobs, 'master'), \
                 patch.object(jobs.JobState, 'set_logfile', side_effect=AssertionError('Legacy file must not open')):
                for program in ('first_program', 'second_program'):
                    self.assertTrue(jobs.start_job(meter.host, program, {}, log=False)[0])
                    jobs._threads[meter.host].join(3)
                    self.assertFalse(jobs._threads[meter.host].is_alive())
                    self.assertEqual(jobs._state(meter.host).logfile_path, supervisor.log_path)
                    self.assertIsNone(session.owner)
            supervisor.close()
            path = Path(supervisor.log_path)
            text = path.read_text(encoding='utf-8')
            for program in ('first_program', 'second_program'):
                self.assertIn(f'RUNNING {program.upper()}', text)
                self.assertIn(f'FINISHED {program.upper()}', text)
                self.assertIn(f'payload for {program}', text)
            self.assertEqual(text.count('=== JOB SUMMARY ==='), 2)
            self.assertEqual(list(Path(temporary).rglob('*.log')), [path])

    def test_debug_and_ui_flags_are_live_and_environment_override_is_explicit(self):
        supervisor = self.supervisor()
        supervisor._log = Mock()
        settings = store.settings.model_copy(deep=True)
        with patch.object(store, '_settings', settings), \
             patch.dict('os.environ', {}, clear=True), patch('builtins.print') as console:
            settings.meter_monitoring.debug = False
            supervisor._debug('first')
            supervisor._log.assert_not_called()
            settings.meter_monitoring.debug = True
            supervisor._debug('second')
            supervisor._log.assert_called_once()
            console.assert_called_once()
            self.assertTrue(supervisor.capture_ui)
            settings.meter_monitoring.capture_ui = False
            self.assertFalse(supervisor.capture_ui)
            with patch.dict('os.environ', {'METER_SUPERVISOR_DEBUG': '0', 'METER_CAPTURE_UI': '1'}):
                self.assertFalse(supervisor.debug_enabled)
                self.assertTrue(supervisor.capture_ui)

    def test_concurrent_job_workers_write_complete_entries(self):
        with tempfile.TemporaryDirectory() as temporary, patch('lib.meter.supervisor.LOG_ROOT', Path(temporary)):
            supervisor = self.supervisor()
            supervisor._log('session_started')
            shared = SharedState()
            shared.set_session_log(supervisor)
            workers = [threading.Thread(target=lambda n=n: [shared.log(f'worker-{n}-{i}', source='worker') for i in range(20)]) for n in range(3)]
            for worker in workers: worker.start()
            for worker in workers: worker.join(2)
            supervisor.close()
            lines = Path(supervisor.log_path).read_text(encoding='utf-8').splitlines()
            messages = [line.split('worker: ')[1] for line in lines if 'worker: ' in line]
            self.assertEqual(len(messages), 60)
            self.assertEqual(len(set(messages)), 60)


if __name__ == '__main__':
    unittest.main()
