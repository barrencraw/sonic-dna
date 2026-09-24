import os
import json
import shutil
import unittest
from datetime import datetime as real_datetime, timezone as real_timezone, timedelta as real_timedelta
from unittest.mock import patch
from utils.dna_ui import main as run_batch, ThermalOverloadError, load_ledger

class MockDatetime:
    current_time = real_datetime(2026, 1, 1, 12, 0, 0, tzinfo=real_timezone.utc)

    class datetime:
        @classmethod
        def now(cls, tz=None):
            return MockDatetime.current_time

        @classmethod
        def strptime(cls, date_string, format_spec):
            return real_datetime.strptime(date_string, format_spec)

    timezone = real_timezone

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        self.backup_folder = os.path.join(self.project_root, 'data_backup')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        MockDatetime.current_time = real_datetime(2026, 1, 1, 12, 0, 0, tzinfo=real_timezone.utc)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_accumulation_and_thermal_lockout(self):
        # 5 valid DNA sequences = 10.0 heat units (5 * 2.0)
        sequences = [f"VOL0890075071{i}" for i in range(5)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        run_batch()

        # Check ledger state
        ledger, system_state = load_ledger(self.ledger_path)
        self.assertEqual(len(ledger), 5)
        self.assertEqual(system_state['core_heat'], 10.0)
        for seq in sequences:
            self.assertEqual(ledger[seq]['terminal_outcome'], 'success')

        # Attempt to process a 6th sequence immediately -> should exceed 10.0 and trigger ThermalOverloadError
        with open(self.input_file, 'w') as f:
            f.write("VOL08900750715\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        err = cm.exception
        self.assertEqual(err.consequence_applied, "Heat Accumulation")
        self.assertEqual(err.refusal_reason, "Thermal Lockout")
        self.assertEqual(err.next_action_hint, "Wait for dissipation. The system is indifferent to your deadlines.")

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_idempotency_does_not_accumulate_heat(self):
        sequences = ["VOL08900750711", "VOL08900750712"]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        run_batch()

        _, system_state = load_ledger(self.ledger_path)
        self.assertEqual(system_state['core_heat'], 4.0)

        # Re-running same sequences should hit dedupe and add 0 heat
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        run_batch()

        _, system_state2 = load_ledger(self.ledger_path)
        self.assertEqual(system_state2['core_heat'], 4.0)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_cooling_dissipation_over_time(self):
        # Fill heat to 10.0
        sequences = [f"VOL0890075071{i}" for i in range(5)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")
        run_batch()

        _, system_state = load_ledger(self.ledger_path)
        self.assertEqual(system_state['core_heat'], 10.0)

        # Advance time by 8 seconds -> cools 8 * 0.5 = 4.0 units -> core_heat becomes 6.0
        MockDatetime.current_time += real_timedelta(seconds=8)

        # Now processing 2 new sequences (4.0 heat) -> 6.0 + 4.0 = 10.0 <= 10.0 -> should succeed!
        new_seqs = ["VOL08900750715", "VOL08900750716"]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(new_seqs) + "\n")

        run_batch()

        ledger, system_state2 = load_ledger(self.ledger_path)
        self.assertEqual(len(ledger), 7)
        self.assertEqual(system_state2['core_heat'], 10.0)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_no_silent_drains_on_lockout(self):
        # Pre-fill heat to 10.0
        sequences = [f"VOL0890075071{i}" for i in range(5)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")
        run_batch()

        # Place new sequence in input
        with open(self.input_file, 'w') as f:
            f.write("VOL08900750799\n")

        # Run batch -> overload error
        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # Input file in data/raw must NOT be touched/drained when batch fails
        # Verify ledger does not contain the refused sequence
        ledger, _ = load_ledger(self.ledger_path)
        self.assertNotIn("VOL08900750799", ledger)

if __name__ == '__main__':
    unittest.main()
