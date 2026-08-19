import os
import json
import shutil
import unittest
import datetime
from unittest.mock import patch
from utils.dna_ui import main as run_batch, ThermalOverloadError, load_ledger

class MockDatetime:
    timezone = datetime.timezone
    current_time = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

    class datetime:
        @classmethod
        def now(cls, tz=None):
            return MockDatetime.current_time

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

        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        MockDatetime.current_time = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_accumulation_and_idempotency(self):
        dna1 = "VOL08900750712"
        dna2 = "VOL00000000000"

        with open(self.input_file, 'w') as f:
            f.write(f"{dna1}\n{dna2}\n")

        run_batch()

        ledger = load_ledger(self.ledger_path)
        state = ledger.get('system_state', {})
        self.assertEqual(state.get('core_heat'), 4.0)

        with open(self.input_file, 'w') as f:
            f.write(f"{dna1}\n{dna2}\n")

        run_batch()

        ledger = load_ledger(self.ledger_path)
        state = ledger.get('system_state', {})
        self.assertEqual(state.get('core_heat'), 4.0, "Duplicate sequences should not add heat")

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_thermal_lockout_and_ui_message_keys(self):
        dnas = [f"VOL0890075071{i}" for i in range(6)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        with self.assertRaises(ThermalOverloadError) as ctx:
            run_batch()

        err = ctx.exception
        self.assertEqual(err.consequence_applied, "Heat Accumulation")
        self.assertEqual(err.refusal_reason, "Thermal Lockout")
        self.assertEqual(err.next_action_hint, "Wait for dissipation. The system is indifferent to your deadlines.")

        ledger = load_ledger(self.ledger_path)
        state = ledger.get('system_state', {})
        self.assertEqual(state.get('core_heat'), 10.0)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_cooling_dissipation_and_no_silent_drains(self):
        dnas = [f"VOL0890075071{i}" for i in range(5)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        run_batch()

        ledger = load_ledger(self.ledger_path)
        self.assertEqual(ledger['system_state']['core_heat'], 10.0)

        with open(self.input_file, 'w') as f:
            f.write("VOL08900750799\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        MockDatetime.current_time += datetime.timedelta(seconds=4)

        run_batch()

        ledger = load_ledger(self.ledger_path)
        self.assertEqual(ledger['system_state']['core_heat'], 10.0)

if __name__ == '__main__':
    unittest.main()
