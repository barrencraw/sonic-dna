import os
import json
import shutil
import unittest
import time
import datetime
from unittest.mock import patch
from utils.dna_ui import main as run_batch, ThermalOverloadError, load_ledger

class MockDatetime(datetime.datetime):
    current_time = datetime.datetime(2026, 8, 15, 12, 0, 0, tzinfo=datetime.timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.current_time

    @classmethod
    def advance_seconds(cls, seconds):
        cls.current_time += datetime.timedelta(seconds=seconds)

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        self.backup_folder = os.path.join(self.project_root, 'data_backup')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        with open(self.ledger_path, 'w') as f:
            json.dump({'ledger': {}, 'system_state': {'core_heat': 0.0, 'last_processed_timestamp': None}}, f)

        MockDatetime.current_time = datetime.datetime(2026, 8, 15, 12, 0, 0, tzinfo=datetime.timezone.utc)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation_and_lockout(self):
        # 5 valid sequences (each adds +2.0 heat = 10.0 heat total)
        # 6th sequence exceeds max threshold (10.0) -> ThermalOverloadError
        sequences = [f"VOL0890075071{i}" for i in range(6)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        with patch('utils.dna_ui.datetime.datetime', MockDatetime):
            with self.assertRaises(ThermalOverloadError) as cm:
                run_batch()

        err_msg = str(cm.exception)
        self.assertIn("Thermal Lockout", err_msg)
        self.assertIn("Heat Accumulation", err_msg)
        self.assertIn("Wait for dissipation. The system is indifferent to your deadlines.", err_msg)

        # Check ledger state
        ledger_data = load_ledger(self.ledger_path)
        system_state = ledger_data.get('system_state', {})
        self.assertEqual(system_state.get('core_heat'), 10.0)

    def test_idempotency_does_not_accumulate_heat(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        with patch('utils.dna_ui.datetime.datetime', MockDatetime):
            run_batch()

        ledger_data = load_ledger(self.ledger_path)
        heat_after_first = ledger_data['system_state']['core_heat']
        self.assertEqual(heat_after_first, 2.0)

        # Run same DNA sequence again
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        with patch('utils.dna_ui.datetime.datetime', MockDatetime):
            run_batch()

        ledger_data_2 = load_ledger(self.ledger_path)
        heat_after_second = ledger_data_2['system_state']['core_heat']
        # Heat should NOT increase because duplicate sequence was skipped
        self.assertEqual(heat_after_second, 2.0)

    def test_heat_dissipation_over_time(self):
        dna1 = "VOL08900750711"
        with open(self.input_file, 'w') as f:
            f.write(dna1 + "\n")

        with patch('utils.dna_ui.datetime.datetime', MockDatetime):
            run_batch()

        ledger_data = load_ledger(self.ledger_path)
        self.assertEqual(ledger_data['system_state']['core_heat'], 2.0)

        # Advance time by 4 seconds (at 0.5 heat/sec decay, 2.0 heat dissipates to 0.0)
        MockDatetime.advance_seconds(4.0)

        dna2 = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna2 + "\n")

        with patch('utils.dna_ui.datetime.datetime', MockDatetime):
            run_batch()

        ledger_data_after = load_ledger(self.ledger_path)
        # 2.0 - (0.5 * 4.0) + 2.0 = 2.0
        self.assertEqual(ledger_data_after['system_state']['core_heat'], 2.0)

    def test_no_silent_drain_on_refusal(self):
        # Fill heat to limit (10.0)
        sequences = [f"VOL0890075071{i}" for i in range(5)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        with patch('utils.dna_ui.datetime.datetime', MockDatetime):
            run_batch()

        # Input file now has a new unprocessed sequence
        new_seq = "VOL08900750719"
        with open(self.input_file, 'w') as f:
            f.write(new_seq + "\n")

        with patch('utils.dna_ui.datetime.datetime', MockDatetime):
            with self.assertRaises(ThermalOverloadError):
                run_batch()

        # Verify input file was NOT cleared (no silent drain)
        with open(self.input_file, 'r') as f:
            content = f.read().strip()
        self.assertEqual(content, new_seq)

if __name__ == '__main__':
    unittest.main()
