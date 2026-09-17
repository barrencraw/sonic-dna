import os
import json
import shutil
import unittest
import datetime as real_datetime
from unittest.mock import patch
from utils.dna_ui import run_batch, ThermalOverloadError, DNAStatus

class MockDatetime(real_datetime.datetime):
    current_time = real_datetime.datetime(2025, 6, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.current_time

class MockDatetimeModule:
    datetime = MockDatetime
    timezone = real_datetime.timezone

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        self.backup_folder = os.path.join(self.project_root, 'data_backup_fatigue')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)
        MockDatetime.current_time = real_datetime.datetime(2025, 6, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_heat_accumulation_and_lockout(self):
        # 5 sequences x 2.0 heat = 10.0 heat. 6th sequence will exceed 10.0 and trigger ThermalOverloadError
        sequences = [f"VOL0890075071{i}" for i in range(6)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(sequences) + "\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch(correlation_id="test-fatigue-lockout")

        self.assertIn("Thermal Lockout", str(cm.exception))
        self.assertIn("Wait for dissipation. The system is indifferent to your deadlines.", str(cm.exception))

        # Check ledger state
        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)

        self.assertIn("system_state", ledger_data)
        system_state = ledger_data["system_state"]
        self.assertEqual(system_state["core_heat"], 10.0)

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_heat_dissipation_over_time(self):
        # Process 4 sequences = 8.0 heat
        sequences = [f"VOL0890075071{i}" for i in range(4)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(sequences) + "\n")

        run_batch(correlation_id="test-fatigue-batch1")

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)
        self.assertEqual(ledger_data["system_state"]["core_heat"], 8.0)

        # Advance time by 8 seconds -> dissipates 8.0 * 0.5 = 4.0 heat -> heat becomes 4.0
        MockDatetime.current_time = real_datetime.datetime(2025, 6, 2, 12, 0, 8, tzinfo=real_datetime.timezone.utc)

        new_sequences = ["TIM01020304050"]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(new_sequences) + "\n")

        run_batch(correlation_id="test-fatigue-batch2")

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)
        # 8.0 - 4.0 + 2.0 = 6.0 heat
        self.assertAlmostEqual(ledger_data["system_state"]["core_heat"], 6.0)

if __name__ == '__main__':
    unittest.main()
