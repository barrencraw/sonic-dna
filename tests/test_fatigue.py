import unittest
import os
import shutil
import tempfile
import json
import datetime
from unittest.mock import patch, MagicMock
from utils.dna_ui import (
    run_batch,
    ThermalOverloadError,
    MSG_KEY_CONSEQUENCE,
    MSG_KEY_REFUSAL_REASON,
    MSG_KEY_NEXT_ACTION_HINT
)

class MockDatetime:
    timezone = datetime.timezone

    class datetime:
        _current_time = datetime.datetime(2025, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls._current_time

        @classmethod
        def strptime(cls, date_string, format_string):
            return datetime.datetime.strptime(date_string, format_string)

        @classmethod
        def set_time(cls, new_time):
            cls._current_time = new_time

        @classmethod
        def advance(cls, seconds):
            cls._current_time += datetime.timedelta(seconds=seconds)

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

        # Mock rule files for Volume (VOL) and Timbre (TIM)
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        with open(os.path.join(self.rules_dir, 'rules_Timbre.json'), 'w') as f:
            json.dump({
                "variable": "Timbre",
                "prefix": "TIM",
                "subvars": {
                    "type": {"description": "timbre type", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Reset mock datetime
        MockDatetime.datetime.set_time(datetime.datetime(2025, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc))

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_accumulation_and_time_dissipation(self):
        """Verify core heat increases with sequence parsing and dissipates over time."""
        # Process 3 sequences (+6.0 heat)
        with open(self.input_file, 'w') as f:
            f.write("VOL001000\nVOL002000\nVOL003000\n")

        run_batch()

        with open(self.ledger_file, 'r') as f:
            data = json.load(f)

        self.assertEqual(data['system_state']['core_heat'], 6.0)

        # Advance time by 4 seconds (-2.0 heat dissipation at 0.5 heat/sec)
        MockDatetime.datetime.advance(4)

        # Process 1 more sequence (+2.0 heat) -> total heat: 6.0 - 2.0 + 2.0 = 6.0
        with open(self.input_file, 'w') as f:
            f.write("TIM001000\n")

        run_batch()

        with open(self.ledger_file, 'r') as f:
            data = json.load(f)

        self.assertEqual(data['system_state']['core_heat'], 6.0)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_idempotency_applied_exactly_once(self):
        """Verify that double invocation on duplicate DNA sequences does NOT accumulate extra heat."""
        dna1 = "VOL001000"
        dna2 = "VOL002000"

        with open(self.input_file, 'w') as f:
            f.write(f"{dna1}\n{dna2}\n")

        run_batch()

        with open(self.ledger_file, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['system_state']['core_heat'], 4.0)

        # Second run with same sequences
        with open(self.input_file, 'w') as f:
            f.write(f"{dna1}\n{dna2}\n")

        run_batch()

        with open(self.ledger_file, 'r') as f:
            data = json.load(f)
        # Heat should remain 4.0 because sequences were deduplicated (skipped)
        self.assertEqual(data['system_state']['core_heat'], 4.0)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_thermal_overload_refusal_and_no_silent_drains(self):
        """Verify thermal lockout refusal when max heat (10.0) is exceeded, and no silent drains occur."""
        # 5 sequences = 10.0 heat (max capacity)
        sequences = [f"VOL00{i}000" for i in range(1, 6)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        run_batch()

        with open(self.ledger_file, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['system_state']['core_heat'], 10.0)

        # Attempt to process a 6th sequence immediately without cooling down -> Overload!
        with open(self.input_file, 'w') as f:
            f.write("TIM099000\n")

        with self.assertRaises(ThermalOverloadError) as ctx:
            run_batch()

        self.assertIn(MSG_KEY_REFUSAL_REASON, str(ctx.exception))
        self.assertIn(MSG_KEY_NEXT_ACTION_HINT, str(ctx.exception))

        # Check that system state remains persisted with core_heat preserved
        with open(self.ledger_file, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['system_state']['core_heat'], 10.0)

        # Verify input file content remains intact (no silent drain on failure)
        with open(self.input_file, 'r') as f:
            self.assertEqual(f.read().strip(), "TIM099000")

if __name__ == '__main__':
    unittest.main()
