import os
import json
import shutil
import unittest
import tempfile
import datetime as dt_module
from unittest.mock import patch

from utils.dna_ui import (
    run_batch,
    ThermalOverloadError,
    DNAProcessingError,
    load_ledger
)

class MockDatetimeClass(dt_module.datetime):
    _now = dt_module.datetime(2026, 3, 2, 12, 0, 0, tzinfo=dt_module.timezone.utc)

    @classmethod
    def set_time(cls, dt):
        cls._now = dt

    @classmethod
    def advance_seconds(cls, seconds):
        cls._now += dt_module.timedelta(seconds=seconds)

    @classmethod
    def now(cls, tz=None):
        return cls._now


class MockDatetimeModule:
    datetime = MockDatetimeClass
    timezone = dt_module.timezone


class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)

        # Copy real rules folder to test sandbox
        real_rules = os.path.join(self.project_root, 'rules')
        shutil.copytree(real_rules, self.rules_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        MockDatetimeClass.set_time(
            dt_module.datetime(2026, 3, 2, 12, 0, 0, tzinfo=dt_module.timezone.utc)
        )

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation_and_lockout_keys(self):
        """Verify heat accumulation (+2.0 heat per sequence) and Thermal Overload keys when threshold is crossed."""
        # 5 valid VOL sequences = +10.0 heat
        sequences = [f"VOL0890075071{i}" for i in range(5)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        # Check core heat in ledger
        ledger_data = load_ledger(self.ledger_file)
        self.assertEqual(ledger_data['system_state']['core_heat'], 10.0)

        # 6th sequence should trigger ThermalOverloadError with exact UI message keys
        with open(self.input_file, 'w') as f:
            f.write("TIM0025000a0100\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            with self.assertRaises(ThermalOverloadError) as cm:
                run_batch()

        err = cm.exception
        self.assertEqual(err.consequence_applied, "Heat Accumulation")
        self.assertEqual(err.refusal_reason, "Thermal Lockout")
        self.assertEqual(err.next_action_hint, "Wait for dissipation. The system is indifferent to your deadlines.")

    def test_idempotency_no_double_heat_accumulation(self):
        """Verify that deduplicated (already processed) sequences do NOT add heat (applied exactly once)."""
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        ledger_data = load_ledger(self.ledger_file)
        initial_heat = ledger_data['system_state']['core_heat']
        self.assertEqual(initial_heat, 2.0)

        # Run again with same sequence
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        ledger_data = load_ledger(self.ledger_file)
        # Heat should remain 2.0 (no duplicate accumulation)
        self.assertEqual(ledger_data['system_state']['core_heat'], 2.0)

    def test_dissipation_and_recovery(self):
        """Verify thermal dissipation (-0.5 heat/sec) permits processing after cooling period."""
        # Accumulate 8.0 heat (4 sequences)
        sequences = [f"VOL0890075071{i}" for i in range(4)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        ledger_data = load_ledger(self.ledger_file)
        self.assertEqual(ledger_data['system_state']['core_heat'], 8.0)

        # Advance time by 10 seconds => dissipates 5.0 heat units (8.0 - 5.0 = 3.0 heat)
        MockDatetimeClass.advance_seconds(10)

        with open(self.input_file, 'w') as f:
            f.write("VOL08900750719\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        ledger_data = load_ledger(self.ledger_file)
        # 3.0 remaining + 2.0 new = 5.0 heat
        self.assertEqual(ledger_data['system_state']['core_heat'], 5.0)

    def test_no_silent_drains(self):
        """Verify that mid-batch lockout re-raises exception and does not drain unprocessed items."""
        # 4 sequences processed = 8.0 heat
        with open(self.input_file, 'w') as f:
            f.write("\n".join([f"VOL0890075071{i}" for i in range(4)]) + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        # Submit 2 sequences: 1st adds 2.0 heat (reaches 10.0), 2nd triggers lockout
        with open(self.input_file, 'w') as f:
            f.write("TIM0025000a0100\nTIM0025000a0101\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            with self.assertRaises(ThermalOverloadError):
                run_batch()

        # Verify second item TIM0025000a0101 was not added to ledger (no silent drain/unrecorded loss)
        ledger_data = load_ledger(self.ledger_file)
        ledger_map = ledger_data.get('ledger', {})
        self.assertNotIn("TIM0025000a0101", ledger_map)


if __name__ == '__main__':
    unittest.main()
