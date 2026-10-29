import os
import json
import shutil
import tempfile
import unittest
import datetime as real_datetime
from unittest.mock import patch

from utils.dna_ui import (
    main as run_batch,
    ThermalOverloadError,
    MSG_CONSEQUENCE,
    MSG_REFUSAL_REASON,
    MSG_NEXT_ACTION_HINT,
    DNAStatus
)

class MockDatetimeModule:
    current_time = real_datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc)

    @classmethod
    def set_time(cls, dt):
        cls.current_time = dt

    @classmethod
    def advance_seconds(cls, seconds):
        cls.current_time += real_datetime.timedelta(seconds=seconds)

    class datetime(real_datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return MockDatetimeModule.current_time

        @classmethod
        def strptime(cls, date_string, format):
            return real_datetime.datetime.strptime(date_string, format)

    timezone = real_datetime.timezone

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')

        # Create valid Volume rule file
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Reset mock time
        MockDatetimeModule.set_time(real_datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc))

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_heat_accumulation(self):
        """Verify each processed DNA sequence increases core heat by 2.0 units."""
        with open(self.input_file, 'w') as f:
            f.write("VOL01000000000\nVOL02000000000\n")

        run_batch()

        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)

        system_state = ledger_data.get('system_state', {})
        self.assertEqual(system_state.get('core_heat'), 4.0, "2 items should accumulate 4.0 heat units")

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_passive_heat_dissipation(self):
        """Verify heat dissipates over time at 0.5 units/sec down to 0.0."""
        # 1. First run generates 4.0 heat
        with open(self.input_file, 'w') as f:
            f.write("VOL01000000000\nVOL02000000000\n")
        run_batch()

        # Advance simulated time by 4 seconds (should dissipate 4 * 0.5 = 2.0 heat units)
        MockDatetimeModule.advance_seconds(4)

        # 2. Run next item
        with open(self.input_file, 'w') as f:
            f.write("VOL03000000000\n")
        run_batch()

        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)

        # Heat was 4.0 -> cooled by 2.0 to 2.0 -> added +2.0 = 4.0
        self.assertEqual(ledger_data['system_state']['core_heat'], 4.0)

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_thermal_lockout_refusal(self):
        """Verify system triggers ThermalOverloadError and message keys when core heat exceeds 10.0 limit."""
        # Submit 6 items at once (6 * 2.0 = 12.0 heat, limit is 10.0)
        sequences = [f"VOL{i:03d}00000000" for i in range(1, 7)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        err_msg = str(cm.exception)
        self.assertIn(MSG_CONSEQUENCE, err_msg)
        self.assertIn(MSG_REFUSAL_REASON, err_msg)
        self.assertIn(MSG_NEXT_ACTION_HINT, err_msg)

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_idempotency_does_not_generate_heat(self):
        """Verify re-submitting already processed items hits deduplication and adds 0.0 heat."""
        dna = "VOL01000000000"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")
        run_batch()

        with open(self.ledger_file, 'r') as f:
            heat1 = json.load(f)['system_state']['core_heat']
        self.assertEqual(heat1, 2.0)

        # Re-submit same sequence without advancing time
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")
        run_batch()

        with open(self.ledger_file, 'r') as f:
            heat2 = json.load(f)['system_state']['core_heat']
        self.assertEqual(heat2, 2.0, "Duplicate sequence should NOT add heat")

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_no_silent_drains(self):
        """Verify partial progress before thermal lockout is saved atomically and exception propagates explicitly."""
        # 5 items = 10.0 heat (max allowed), 6th item triggers lockout
        sequences = [f"VOL{i:03d}00000000" for i in range(1, 7)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # Verify that the 5 processed items before lockout were saved atomically to ledger
        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)

        ledger = ledger_data.get('ledger', {})
        self.assertEqual(len(ledger), 5, "5 items parsed before lockout should be persisted in ledger")
        self.assertEqual(ledger_data['system_state']['core_heat'], 10.0)

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertTrue(os.path.exists(json_out))
        with open(json_out, 'r') as f:
            parsed = json.load(f)
        self.assertEqual(len(parsed), 5)

if __name__ == '__main__':
    unittest.main()
