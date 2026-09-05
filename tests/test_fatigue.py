import os
import json
import shutil
import unittest
import datetime
from unittest.mock import patch
from utils.dna_ui import main as run_batch, ThermalOverloadError, DNAStatus

class MockDatetime:
    timezone = datetime.timezone
    _current_now = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

    class datetime:
        @classmethod
        def now(cls, tz=None):
            return MockDatetime._current_now

        @classmethod
        def strptime(cls, date_string, format_str):
            return datetime.datetime.strptime(date_string, format_str)

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
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        MockDatetime._current_now = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_accumulation_and_lockout(self):
        # 5 valid sequences: each adds 2.0 heat units -> 10.0 triggers lockout
        sequences = [f"VOL0890075071{i}" for i in range(5)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)

        system_state = ledger_data.get('system_state', {})
        self.assertGreaterEqual(system_state.get('core_heat', 0.0), 10.0)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_dissipation_recovers_lockout(self):
        sequences = [f"VOL0890075071{i}" for i in range(5)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        try:
            run_batch()
        except ThermalOverloadError:
            pass

        # Advance simulated time by 20 seconds (20s * 0.5/s = 10.0 heat dissipated)
        MockDatetime._current_now += datetime.timedelta(seconds=20)

        new_sequence = "VOL00000000000"
        with open(self.input_file, 'w') as f:
            f.write(new_sequence + "\n")

        # Run batch after cooling period; should succeed
        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)

        ledger = ledger_data.get('ledger', ledger_data)
        self.assertIn(new_sequence, ledger)
        self.assertEqual(ledger[new_sequence]['terminal_outcome'], DNAStatus.SUCCESS.value)

if __name__ == '__main__':
    unittest.main()
