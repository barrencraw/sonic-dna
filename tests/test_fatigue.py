import os
import json
import shutil
import unittest
import datetime
from unittest.mock import patch
from utils.dna_ui import main as run_batch, ThermalOverloadError

class MockDatetime(datetime.datetime):
    current_time = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.current_time

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        # Backup existing data
        self.backup_folder = os.path.join(self.project_root, 'data_backup_fatigue')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    @patch('utils.dna_ui.datetime')
    def test_thermal_accumulation_and_refusal(self, mock_datetime_module):
        mock_datetime_module.timezone = datetime.timezone
        mock_datetime_module.datetime = MockDatetime
        MockDatetime.current_time = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

        # Batch 1: Process 4 sequences (Heat = +8.0, under threshold 10.0)
        sequences = [f"VOL0890075071{i}" for i in range(4)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)

        self.assertIn("system_state", ledger)
        self.assertEqual(ledger["system_state"]["core_heat"], 8.0)

        # Batch 2: Try 2 more sequences at same time -> 8.0 + 2.0 = 10.0 ok, but second sequence would be 12.0 > 10.0 -> ThermalOverloadError
        more_sequences = ["VOL08900750714", "VOL08900750715"]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(more_sequences) + "\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        err = cm.exception
        self.assertEqual(err.consequence_applied, "Heat Accumulation")
        self.assertEqual(err.refusal_reason, "Thermal Lockout")
        self.assertEqual(err.next_action_hint, "Wait for dissipation. The system is indifferent to your deadlines.")

        # Check that heat reached 10.0 after sequence 4, then blocked sequence 5
        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)

        self.assertEqual(ledger["system_state"]["core_heat"], 10.0)

    @patch('utils.dna_ui.datetime')
    def test_thermal_dissipation_over_time(self, mock_datetime_module):
        mock_datetime_module.timezone = datetime.timezone
        mock_datetime_module.datetime = MockDatetime
        MockDatetime.current_time = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

        # 5 sequences -> 10.0 heat (limit)
        sequences = [f"VOL0890075071{i}" for i in range(5)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertEqual(ledger["system_state"]["core_heat"], 10.0)

        # Advance time by 8 seconds -> dissipation = 8 * 0.5 = 4.0 heat dissipated (remaining heat = 6.0)
        MockDatetime.current_time = datetime.datetime(2026, 3, 2, 12, 0, 8, tzinfo=datetime.timezone.utc)

        # Now processing 2 sequences (6.0 + 2.0 + 2.0 = 10.0) should succeed without lockout
        new_sequences = ["VOL08900750715", "VOL08900750716"]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(new_sequences) + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertEqual(ledger["system_state"]["core_heat"], 10.0)

    @patch('utils.dna_ui.datetime')
    def test_idempotency_no_double_heat(self, mock_datetime_module):
        mock_datetime_module.timezone = datetime.timezone
        mock_datetime_module.datetime = MockDatetime
        MockDatetime.current_time = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

        seq = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(seq + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertEqual(ledger["system_state"]["core_heat"], 2.0)

        # Re-running same sequence should be deduplicated by idempotency key and NOT generate heat
        with open(self.input_file, 'w') as f:
            f.write(seq + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertEqual(ledger["system_state"]["core_heat"], 2.0, "Deduplicated input must not cause heat accumulation")

if __name__ == '__main__':
    unittest.main()
