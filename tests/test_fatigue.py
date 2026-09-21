import os
import json
import shutil
import unittest
import datetime
from unittest.mock import patch
from utils.dna_ui import main as run_batch, ThermalOverloadError, UI_MESSAGES

class MockDatetimeModule:
    def __init__(self, initial_time):
        self._current_time = initial_time
        self.timezone = datetime.timezone

    def set_time(self, new_time):
        self._current_time = new_time

    def advance_seconds(self, seconds):
        self._current_time += datetime.timedelta(seconds=seconds)

    @property
    def datetime(self):
        outer = self
        class _InnerDatetime:
            @classmethod
            def now(cls, tz=None):
                return outer._current_time

            @classmethod
            def strptime(cls, date_string, format_string):
                return datetime.datetime.strptime(date_string, format_string)
        return _InnerDatetime

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

        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)

        self.start_time = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)
        self.mock_dt = MockDatetimeModule(self.start_time)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation_and_lockout(self):
        dnas = [
            "VOL01000000000",
            "VOL02000000000",
            "VOL03000000000",
            "VOL04000000000",
            "VOL05000000000"
        ]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        with patch('utils.dna_ui.datetime', self.mock_dt):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)

        self.assertEqual(ledger_data['system_state']['core_heat'], 10.0)

        dna6 = "VOL06000000000"
        with open(self.input_file, 'w') as f:
            f.write(dna6 + "\n")

        with patch('utils.dna_ui.datetime', self.mock_dt):
            with self.assertRaises(ThermalOverloadError) as cm:
                run_batch()

        self.assertIn(UI_MESSAGES['refusal_reason'], str(cm.exception))
        self.assertIn(UI_MESSAGES['next_action_hint'], str(cm.exception))

    def test_heat_dissipation(self):
        dnas = [f"VOL00{i}00000000" for i in range(5)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        with patch('utils.dna_ui.datetime', self.mock_dt):
            run_batch()

        self.mock_dt.advance_seconds(4)

        dna6 = "VOL09900000000"
        with open(self.input_file, 'w') as f:
            f.write(dna6 + "\n")

        with patch('utils.dna_ui.datetime', self.mock_dt):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)

        self.assertEqual(ledger_data['system_state']['core_heat'], 10.0)

    def test_idempotency_no_heat_accumulation(self):
        dna = "VOL01000000000"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        with patch('utils.dna_ui.datetime', self.mock_dt):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)

        self.assertEqual(ledger_data['system_state']['core_heat'], 2.0)

        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        with patch('utils.dna_ui.datetime', self.mock_dt):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data2 = json.load(f)

        self.assertEqual(ledger_data2['system_state']['core_heat'], 2.0)

if __name__ == '__main__':
    unittest.main()
