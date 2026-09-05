import os
import sys
import json
import shutil
import unittest
import datetime as real_datetime
from unittest.mock import patch, MagicMock

# Mock PySide6 dependencies if needed before importing main/dna_ui
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6

from utils.dna_ui import run_batch, ThermalOverloadError, DNAStatus, load_ledger, save_ledger
import main

class MockDatetime:
    current_time = real_datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc)

    @classmethod
    def now(cls, tz=None):
        if tz is not None:
            return cls.current_time.astimezone(tz)
        return cls.current_time

    @classmethod
    def strptime(cls, date_string, format_spec):
        return real_datetime.datetime.strptime(date_string, format_spec)

    @classmethod
    def advance(cls, seconds):
        cls.current_time += real_datetime.timedelta(seconds=seconds)

class MockDatetimeModule:
    datetime = MockDatetime
    timezone = real_datetime.timezone

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        MockDatetime.current_time = real_datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc)
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

        self.rules_folder = os.path.join(self.project_root, 'rules')

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_heat_accumulation_and_lockout(self):
        """Test that each sequence adds 2.0 heat units and heat >= 10.0 causes ThermalOverloadError."""
        # 5 valid volume sequences (5 * 2.0 = 10.0 heat)
        dnas = [
            "VOL00000000000",
            "VOL00000000001",
            "VOL00000000002",
            "VOL00000000003",
            "VOL00000000004"
        ]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        run_batch()

        _, state = load_ledger(self.ledger_path)
        self.assertAlmostEqual(state['core_heat'], 10.0)

        # 6th sequence should trigger Thermal lockout on initial check
        with open(self.input_file, 'w') as f:
            f.write("VOL00000000005\n")

        with self.assertRaises(ThermalOverloadError) as ctx:
            run_batch()

        err = ctx.exception
        self.assertEqual(err.consequence_applied, "Heat Accumulation")
        self.assertEqual(err.refusal_reason, "Thermal Lockout")
        self.assertEqual(err.next_action_hint, "Wait for dissipation. The system is indifferent to your deadlines.")

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_thermal_dissipation(self):
        """Test that simulated time advancement cools down core heat at 0.5 units/sec."""
        # Process 4 sequences -> 8.0 heat
        dnas = [f"VOL0000000000{i}" for i in range(4)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        run_batch()

        _, state = load_ledger(self.ledger_path)
        self.assertAlmostEqual(state['core_heat'], 8.0)

        # Advance simulated time by 10 seconds (10 * 0.5 = 5.0 decay -> 3.0 heat remaining)
        MockDatetime.advance(10.0)

        # Process another sequence
        with open(self.input_file, 'w') as f:
            f.write("VOL00000000004\n")

        run_batch()

        _, state = load_ledger(self.ledger_path)
        self.assertAlmostEqual(state['core_heat'], 5.0) # (8.0 - 5.0) + 2.0 = 5.0

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_idempotency_no_heat_accumulation(self):
        """Test that deduplicated sequences do not cause heat accumulation."""
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()
        _, state = load_ledger(self.ledger_path)
        self.assertAlmostEqual(state['core_heat'], 2.0)

        # Process same DNA again
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()
        _, state = load_ledger(self.ledger_path)
        self.assertAlmostEqual(state['core_heat'], 2.0, msg="Deduped sequence should not increase heat")

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_no_silent_drains_on_lockout(self):
        """Test that when lockout occurs during process_once, input file is NOT cleared."""
        # Set core heat to 10.0 in ledger
        save_ledger(self.ledger_path, {}, {'core_heat': 10.0, 'last_processed_timestamp': '2026-03-02T12:00:00Z'})

        with open(self.input_file, 'w') as f:
            f.write("VOL08900750712\n")

        with self.assertRaises(SystemExit):
            main.process_once()

        # Input file must still contain the sequence
        with open(self.input_file, 'r') as f:
            content = f.read().strip()
        self.assertEqual(content, "VOL08900750712")

if __name__ == '__main__':
    unittest.main()
