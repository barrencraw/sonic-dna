import os
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from utils.dna_ui import (
    run_batch,
    ThermalOverloadError,
    MSG_HEAT_ACCUMULATION,
    MSG_THERMAL_LOCKOUT,
    MSG_NEXT_ACTION_HINT
)

class MockDatetime:
    timezone = timezone
    current_time = datetime(2025, 6, 2, 12, 0, 0, tzinfo=timezone.utc)

    class datetime:
        @classmethod
        def now(cls, tz=None):
            return MockDatetime.current_time

        @classmethod
        def strptime(cls, date_string, format_spec):
            return datetime.strptime(date_string, format_spec)

    @classmethod
    def advance_seconds(cls, seconds):
        cls.current_time += timedelta(seconds=seconds)

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

        # Volume rule
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "amp": {"min": 0, "max": 1000, "pad": 4, "description": "amp"},
                    "lr": {"min": 0, "max": 100, "pad": 3, "description": "lr"},
                    "sur": {"min": 0, "max": 10, "pad": 2, "description": "sur"},
                    "head": {"min": 0, "max": 60, "pad": 2, "description": "head"}
                }
            }, f)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)
        MockDatetime.current_time = datetime(2025, 6, 2, 12, 0, 0, tzinfo=timezone.utc)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    @patch('utils.dna_ui.datetime', MockDatetime.datetime)
    def test_heat_accumulation_and_lockout(self):
        # Generate 6 sequences -> 5 process (heat = 10.0), 6th triggers lockout
        sequences = [f"VOL08900750{i:02d}" for i in range(10, 16)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch(correlation_id="test-fatigue-lockout")

        err_msg = str(cm.exception)
        self.assertIn(MSG_HEAT_ACCUMULATION, err_msg)
        self.assertIn(MSG_THERMAL_LOCKOUT, err_msg)
        self.assertIn(MSG_NEXT_ACTION_HINT, err_msg)

        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)

        system_state = ledger_data.get('system_state', {})
        self.assertEqual(system_state.get('core_heat'), 10.0)

    @patch('utils.dna_ui.datetime', MockDatetime.datetime)
    def test_thermal_dissipation(self):
        # 5 sequences -> heat = 10.0
        sequences = [f"VOL08900750{i:02d}" for i in range(10, 15)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        run_batch(correlation_id="test-fatigue-fill")

        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)
        self.assertEqual(ledger_data.get('system_state', {}).get('core_heat'), 10.0)

        # Simulate 10 seconds cooling @ 0.5 heat/sec -> 5.0 heat dissipated -> core_heat = 5.0
        MockDatetime.advance_seconds(10)

        # Process 1 new sequence (5.0 + 2.0 = 7.0 heat) -> should succeed
        new_seq = "VOL0890075099"
        with open(self.input_file, 'w') as f:
            f.write(new_seq + "\n")

        run_batch(correlation_id="test-fatigue-post-cooling")

        with open(self.ledger_file, 'r') as f:
            ledger_data2 = json.load(f)
        self.assertEqual(ledger_data2.get('system_state', {}).get('core_heat'), 7.0)

if __name__ == '__main__':
    unittest.main()
