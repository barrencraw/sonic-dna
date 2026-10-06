import os
import json
import shutil
import tempfile
import unittest
from datetime import datetime as real_datetime, timezone as real_timezone
from unittest.mock import patch

from utils.dna_ui import main as run_batch, ThermalOverloadError, load_ledger

class MockDatetimeModule:
    """Mock module structure for datetime patching."""
    timezone = real_timezone

    class datetime:
        current_time = real_datetime(2025, 1, 1, 12, 0, 0, tzinfo=real_timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.current_time

        @classmethod
        def strptime(cls, date_string, format_string):
            return real_datetime.strptime(date_string, format_string)

        @classmethod
        def advance_seconds(cls, seconds):
            cls.current_time = real_datetime.fromtimestamp(
                cls.current_time.timestamp() + seconds, tz=real_timezone.utc
            )


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

        # Mock Volume rule
        rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(rule_file, 'w') as f:
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
        MockDatetimeModule.datetime.current_time = real_datetime(2025, 1, 1, 12, 0, 0, tzinfo=real_timezone.utc)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation_and_lockout(self):
        # 6 valid sequences: 5 sequences add 10.0 heat, 6th sequence (12.0 heat > 10.0 limit) triggers lockout
        sequences = [
            "VOL08900750712",
            "VOL08900750713",
            "VOL08900750714",
            "VOL08900750715",
            "VOL08900750716",
            "VOL08900750717"
        ]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            with self.assertRaises(ThermalOverloadError) as cm:
                run_batch()

        err = cm.exception
        self.assertEqual(ThermalOverloadError.CONSEQUENCE_APPLIED, "Heat Accumulation")
        self.assertEqual(ThermalOverloadError.REFUSAL_REASON, "Thermal Lockout")
        self.assertEqual(ThermalOverloadError.NEXT_ACTION_HINT, "Wait for dissipation. The system is indifferent to your deadlines.")
        self.assertIn("Thermal Lockout", str(err))
        self.assertIn("Heat Accumulation", str(err))
        self.assertIn("Wait for dissipation", str(err))

        ledger, system_state = load_ledger(self.ledger_file)
        # 5 sequences were processed prior to lockout
        self.assertEqual(len(ledger), 5)
        self.assertEqual(system_state['core_heat'], 10.0)

    def test_idempotency_does_not_add_heat(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        _, system_state_1 = load_ledger(self.ledger_file)
        self.assertEqual(system_state_1['core_heat'], 2.0)

        # Second run with same deduplicated sequence
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        _, system_state_2 = load_ledger(self.ledger_file)
        self.assertEqual(system_state_2['core_heat'], 2.0, "Deduplicated sequence should not add heat")

    def test_heat_dissipation_over_time(self):
        # 5 sequences = 10.0 heat
        sequences = [f"VOL0890075071{i}" for i in range(5)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        _, system_state = load_ledger(self.ledger_file)
        self.assertEqual(system_state['core_heat'], 10.0)

        # Advance time by 10 seconds (0.5 heat/sec * 10s = 5.0 heat dissipated -> remaining heat = 5.0)
        MockDatetimeModule.datetime.advance_seconds(10)

        # Now run a new sequence (5.0 + 2.0 = 7.0 <= 10.0 threshold)
        new_dna = "VOL08900750799"
        with open(self.input_file, 'w') as f:
            f.write(new_dna + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        _, system_state_after = load_ledger(self.ledger_file)
        self.assertEqual(system_state_after['core_heat'], 7.0)


if __name__ == '__main__':
    unittest.main()
