import os
import json
import shutil
import unittest
import datetime
from unittest.mock import patch, MagicMock

import utils.dna_ui
from utils.dna_ui import (
    run_batch,
    load_ledger,
    ThermalOverloadError,
    REFUSAL_REASON_KEY,
    NEXT_ACTION_HINT_KEY,
    CONSEQUENCE_APPLIED_KEY
)

class MockDatetime:
    timezone = datetime.timezone
    _current_time = datetime.datetime(2025, 6, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

    class datetime:
        @classmethod
        def now(cls, tz=None):
            return MockDatetime._current_time

        @classmethod
        def strptime(cls, date_string, format_string):
            return datetime.datetime.strptime(date_string, format_string)

    @classmethod
    def advance_seconds(cls, seconds):
        cls._current_time += datetime.timedelta(seconds=seconds)


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

        MockDatetime._current_time = datetime.datetime(2025, 6, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_accumulation_applied_exactly_once(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # First run: new sequence adds 2.0 heat
        processed = run_batch()
        self.assertEqual(processed, 1)

        ledger = load_ledger(self.ledger_path)
        self.assertEqual(ledger['system_state']['core_heat'], 2.0)

        # Second run: same sequence is deduplicated (idempotency hit), 0 heat added
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        processed = run_batch()
        self.assertEqual(processed, 0)

        ledger = load_ledger(self.ledger_path)
        self.assertEqual(ledger['system_state']['core_heat'], 2.0)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_thermal_lockout_refusal(self):
        # 5 valid sequences = 10.0 heat (threshold reached)
        dnas = [f"VOL089007507{i:02d}" for i in range(5)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        run_batch()

        ledger = load_ledger(self.ledger_path)
        self.assertEqual(ledger['system_state']['core_heat'], 10.0)

        # Adding a 6th sequence should trigger ThermalOverloadError
        new_dna = "VOL08900750799"
        with open(self.input_file, 'w') as f:
            f.write(new_dna + "\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        self.assertIn(REFUSAL_REASON_KEY, str(cm.exception))
        self.assertIn(NEXT_ACTION_HINT_KEY, str(cm.exception))

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_dissipation_over_time(self):
        # Accumulate 8.0 heat
        dnas = [f"VOL089007507{i:02d}" for i in range(4)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        run_batch()
        ledger = load_ledger(self.ledger_path)
        self.assertEqual(ledger['system_state']['core_heat'], 8.0)

        # Advance time by 10 seconds => cools 10 * 0.5 = 5.0 heat => remaining heat = 3.0
        MockDatetime.advance_seconds(10)

        new_dna = "VOL08900750799"
        with open(self.input_file, 'w') as f:
            f.write(new_dna + "\n")

        processed = run_batch()
        self.assertEqual(processed, 1)

        ledger = load_ledger(self.ledger_path)
        # 8.0 - 5.0 + 2.0 = 5.0
        self.assertEqual(ledger['system_state']['core_heat'], 5.0)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_no_silent_drains_on_lockout(self):
        import main

        # Push heat to 10.0
        dnas = [f"VOL089007507{i:02d}" for i in range(5)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        run_batch()

        # Add new DNA sequence to input file while locked out
        new_dna = "VOL08900750799"
        with open(self.input_file, 'w') as f:
            f.write(new_dna + "\n")

        # Execute process_once via main module (which catches error and exits with code 1)
        with patch.object(main, '__file__', os.path.join(self.project_root, 'main.py')):
            with self.assertRaises(SystemExit) as cm:
                main.process_once()
            self.assertEqual(cm.exception.code, 1)

        # Verify that input file was NOT cleared (no silent drains)
        with open(self.input_file, 'r') as f:
            contents = f.read().strip()
        self.assertEqual(contents, new_dna)


if __name__ == '__main__':
    unittest.main()
