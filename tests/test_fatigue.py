import os
import json
import shutil
import unittest
import datetime
from unittest.mock import patch
from utils.dna_ui import run_batch, ThermalOverloadError


class FakeDateTime:
    current_time = datetime.datetime(2025, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.current_time

    @classmethod
    def strptime(cls, date_string, format_spec):
        return datetime.datetime.strptime(date_string, format_spec)


class MockDatetimeModule:
    timezone = datetime.timezone
    datetime = FakeDateTime


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
        with open(self.ledger_path, 'w') as f:
            json.dump({'ledger': {}, 'system_state': {'core_heat': 0.0, 'last_processed_timestamp': None}}, f)

        FakeDateTime.current_time = datetime.datetime(2025, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_heat_accumulation_and_lockout(self):
        sequences = [f"VOL08900750{i:03d}" for i in range(6)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)

        state = ledger_data.get('system_state', {})
        self.assertGreaterEqual(state.get('core_heat', 0.0), 10.0)

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_cooling_dissipation(self):
        sequences = [f"VOL08900750{i:03d}" for i in range(4)]  # 4 * 2 = 8 heat
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)
        self.assertEqual(ledger_data['system_state']['core_heat'], 8.0)

        # Fast-forward simulated time by 10 seconds (10 * 0.5 = 5.0 heat dissipated -> 3.0 heat remaining)
        FakeDateTime.current_time += datetime.timedelta(seconds=10)

        new_sequences = ["VOL08900750999"]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(new_sequences) + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data2 = json.load(f)
        self.assertEqual(ledger_data2['system_state']['core_heat'], 5.0)  # 3.0 + 2.0 = 5.0


if __name__ == '__main__':
    unittest.main()
