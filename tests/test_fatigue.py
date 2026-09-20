import os
import json
import shutil
import unittest
import tempfile
import datetime
from unittest.mock import patch
import utils.dna_ui
from utils.dna_ui import (
    main as run_batch,
    ThermalOverloadError,
    UI_MSG_CONSEQUENCE_APPLIED,
    UI_MSG_REFUSAL_REASON,
    UI_MSG_NEXT_ACTION_HINT,
    MAX_CORE_HEAT,
    HEAT_PER_PARSE,
    DISSIPATION_RATE_PER_SEC
)

class MockDatetimeModule:
    timezone = datetime.timezone
    class datetime:
        @classmethod
        def now(cls, tz=None):
            return MockDatetimeModule.current_now
        @classmethod
        def strptime(cls, date_string, format_spec):
            return datetime.datetime.strptime(date_string, format_spec)

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

        # Mock a Volume rule
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

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation_and_lockout(self):
        """Test heat accumulates per parsed sequence and triggers lockout at MAX_CORE_HEAT (10.0)."""
        sequences = [f"VOL{i:03d}00000000" for i in range(1, 7)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        with self.assertRaises(ThermalOverloadError) as ctx:
            run_batch()

        err_msg = str(ctx.exception)
        self.assertIn(UI_MSG_REFUSAL_REASON, err_msg)
        self.assertIn(UI_MSG_NEXT_ACTION_HINT, err_msg)

        # Check ledger state
        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)

        processed_count = len(ledger_data['ledger'])
        self.assertEqual(processed_count, 5, "Exactly 5 sequences should have been processed before reaching lockout threshold (10.0 heat)")
        self.assertEqual(ledger_data['system_state']['core_heat'], 10.0)

    def test_idempotency_applied_exactly_once(self):
        """Test that already processed sequences are skipped and do NOT add heat again (applied exactly once)."""
        dna = "VOL00100000000"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)

        first_heat = ledger_data['system_state']['core_heat']
        self.assertEqual(first_heat, 2.0)

        # Second invocation with same DNA sequence
        run_batch()

        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)

        second_heat = ledger_data['system_state']['core_heat']
        self.assertEqual(second_heat, 2.0, "Re-processing duplicate DNA sequence must NOT add additional heat")

    def test_heat_dissipation_and_no_silent_drains(self):
        """Test that heat dissipates over time and no unexpected silent heat drains occur."""
        dna1 = "VOL00100000000"
        with open(self.input_file, 'w') as f:
            f.write(dna1 + "\n")

        base_time = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
        MockDatetimeModule.current_now = base_time

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)
        self.assertEqual(ledger_data['system_state']['core_heat'], 2.0)

        # 2 seconds later -> 2 * 0.5 = 1.0 dissipated -> remaining heat = 1.0
        later_time = base_time + datetime.timedelta(seconds=2)
        MockDatetimeModule.current_now = later_time

        dna2 = "VOL00200000000"
        with open(self.input_file, 'w') as f:
            f.write(dna2 + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)

        # 2.0 initial - 1.0 dissipation + 2.0 new parse = 3.0 core heat
        self.assertEqual(ledger_data['system_state']['core_heat'], 3.0)

if __name__ == '__main__':
    unittest.main()
