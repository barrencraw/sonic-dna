import os
import json
import shutil
import unittest
import tempfile
import io
import sys
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from utils.dna_ui import run_batch, ThermalOverloadError

class MockDatetime(datetime):
    _current_time = datetime(2026, 3, 2, 10, 0, 0, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls._current_time

    @classmethod
    def set_time(cls, new_time):
        cls._current_time = new_time

    @classmethod
    def advance_seconds(cls, seconds):
        cls._current_time += timedelta(seconds=seconds)

class MockDatetimeModule:
    datetime = MockDatetime
    timezone = timezone

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

        # Mock Volume rule
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)
        MockDatetime.set_time(datetime(2026, 3, 2, 10, 0, 0, tzinfo=timezone.utc))

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    @patch('utils.dna_ui.datetime', MockDatetimeModule.datetime)
    def test_heat_accumulation_and_lockout(self):
        # 5 valid sequences -> 5 * 2.0 = 10.0 heat units (lockout)
        sequences = [f"VOL00{i}" for i in range(6)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        stdout_capture = io.StringIO()
        with patch('sys.stdout', stdout_capture):
            with self.assertRaises(ThermalOverloadError):
                run_batch()

        output = stdout_capture.getvalue()
        self.assertIn("Heat Accumulation", output)
        self.assertIn("Thermal Lockout", output)
        self.assertIn("Wait for dissipation. The system is indifferent to your deadlines.", output)

        # Verify ledger saved heat state
        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)

        system_state = ledger_data.get('system_state', {})
        self.assertGreaterEqual(system_state.get('core_heat', 0.0), 10.0)

    @patch('utils.dna_ui.datetime', MockDatetimeModule.datetime)
    def test_heat_dissipation_over_time(self):
        # 4 sequences = 8.0 heat
        sequences = [f"VOL00{i}" for i in range(4)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)
        self.assertEqual(ledger_data['system_state']['core_heat'], 8.0)

        # Advance time by 10 seconds (10 * 0.5 = 5.0 heat dissipated -> 3.0 heat remaining)
        MockDatetime.advance_seconds(10)

        # Process 1 new sequence (adds 2.0 heat -> 5.0 total heat, well under 10.0)
        with open(self.input_file, 'w') as f:
            f.write("VOL099\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)
        self.assertAlmostEqual(ledger_data['system_state']['core_heat'], 5.0)

if __name__ == '__main__':
    unittest.main()
