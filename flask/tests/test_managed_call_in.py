"""A restart during the call-in trigger must preserve its original transaction."""
from importlib import import_module
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from lib.automation.shared_state import SharedState
from lib.automation.recovery import run_subtest
from lib.meter.lifecycle import MeterSession, MeterInterrupted


call_in = import_module('lib.automation.tests.cycle_call_in')


class ManagedCallInTests(unittest.TestCase):
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
