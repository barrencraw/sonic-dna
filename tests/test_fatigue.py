import os
import json
import shutil
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import utils.dna_ui as dna_ui
from utils.dna_ui import run_batch, ThermalOverloadError

class MockDatetime:
    current_time = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    timezone = timezone

    @classmethod
    def now(cls, tz=None):
        return cls.current_time

    @classmethod
    def strptime(cls, date_string, format_string):
        return datetime.strptime(date_string, format_string)

class TestThermalFatigueSystem(unittest.TestCase):
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
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        MockDatetime.current_time = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_accumulation_and_lockout(self):
        # 6 valid DNA sequences: each adds 2.0 heat units.
        # 6th sequence (VOL00000000006) exceeds threshold (12.0 > 10.0) -> triggers ThermalOverloadError.
        sequences = [f"VOL0890075071{i}" for i in range(1, 7)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(sequences) + "\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        err_msg = str(cm.exception)
        self.assertIn("Thermal Lockout", err_msg)
        self.assertIn("Heat Accumulation", err_msg)
        self.assertIn("Wait for dissipation. The system is indifferent to your deadlines.", err_msg)

        # Verify ledger state saved heat accumulation without committing unwritten batch outputs
        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)

        ledger = ledger_data.get('ledger', {})
        system_state = ledger_data.get('system_state', {})

        self.assertEqual(len(ledger), 0, "Batch should be aborted and rolled back to maintain consistency with unwritten output files")
        self.assertAlmostEqual(system_state.get('core_heat', 0.0), 10.0)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_dissipation_over_time_allows_recovery(self):
        # 4 sequences -> 8.0 heat units
        sequences1 = [f"VOL0890075071{i}" for i in range(1, 5)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(sequences1) + "\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)
        self.assertAlmostEqual(ledger_data['system_state']['core_heat'], 8.0)

        # Advance simulated time by 10 seconds -> 10 * 0.5 = 5.0 heat dissipated -> 3.0 heat left
        MockDatetime.current_time += timedelta(seconds=10)

        # Add 2 more sequences (adds 4.0 heat -> 7.0 heat total, well below 10.0 lockout threshold)
        sequences2 = [f"VOL0890075071{i}" for i in range(5, 7)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(sequences2) + "\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)

        self.assertEqual(len(ledger_data['ledger']), 6)
        self.assertAlmostEqual(ledger_data['system_state']['core_heat'], 7.0)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_idempotency_does_not_accumulate_heat_on_deduplicated_input(self):
        dna = "VOL08900750711"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)
        self.assertAlmostEqual(ledger_data['system_state']['core_heat'], 2.0)

        # Re-run batch with same sequence without advancing time
        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)

        # Deduplication hit -> no new processing, core heat remains 2.0
        self.assertAlmostEqual(ledger_data['system_state']['core_heat'], 2.0)

if __name__ == '__main__':
    unittest.main()
