import os
import sys
import json
import shutil
import tempfile
import unittest
import datetime
from unittest.mock import patch, MagicMock

from utils.dna_ui import run_batch, ThermalOverloadError, UI_MESSAGES


class MockDatetimeInner:
    current_time = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.current_time

    @classmethod
    def strptime(cls, date_string, format_string):
        return datetime.datetime.strptime(date_string, format_string)

class MockDatetimeModule:
    timezone = datetime.timezone
    datetime = MockDatetimeInner


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

        MockDatetimeInner.current_time = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_heat_accumulation_and_lockout(self):
        sequences = [f"VOL0890075071{i}" for i in range(6)]

        # Write 5 sequences -> 5 * 2.0 = 10.0 heat
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences[:5]) + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)

        self.assertEqual(ledger_data['system_state']['core_heat'], 10.0)

        # Attempt 6th sequence when core_heat >= 10.0 -> Thermal Lockout
        with open(self.input_file, 'w') as f:
            f.write(sequences[5] + "\n")

        with self.assertRaises(ThermalOverloadError) as ctx:
            run_batch()

        self.assertIn(UI_MESSAGES["refusal_reason"], str(ctx.exception))

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_dissipation_over_time(self):
        sequences = [f"VOL0890075071{i}" for i in range(6)]

        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences[:5]) + "\n")

        run_batch()

        # Advance simulated time by 10 seconds -> 10 * 0.5 = 5.0 heat dissipated
        MockDatetimeInner.current_time += datetime.timedelta(seconds=10)

        with open(self.input_file, 'w') as f:
            f.write(sequences[5] + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)

        # 10.0 - 5.0 + 2.0 = 7.0
        self.assertEqual(ledger_data['system_state']['core_heat'], 7.0)

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_idempotency_no_extra_heat(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)

        heat_after_first = ledger_data['system_state']['core_heat']
        self.assertEqual(heat_after_first, 2.0)

        # Double invocation with same DNA sequence
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data_2 = json.load(f)

        self.assertEqual(ledger_data_2['system_state']['core_heat'], 2.0)

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_no_silent_drains_on_lockout(self):
        sequences = [f"VOL0890075071{i}" for i in range(5)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        run_batch()

        locked_seq = "VOL08900750799"
        with open(self.input_file, 'w') as f:
            f.write(locked_seq + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        with open(self.input_file, 'r') as f:
            content = f.read().strip()
        self.assertEqual(content, locked_seq)


if __name__ == '__main__':
    unittest.main()
