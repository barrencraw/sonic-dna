import os
import json
import shutil
import unittest
import datetime
from unittest.mock import patch
from utils.dna_ui import run_batch, ThermalOverloadError, DNAStatus, UI_FEEDBACK

class MockDatetime:
    """A mock implementation of datetime to control elapsed time deterministically."""
    current_time = datetime.datetime(2025, 6, 15, 12, 0, 0)

    @classmethod
    def set_time(cls, dt):
        cls.current_time = dt

    @classmethod
    def advance_seconds(cls, seconds):
        cls.current_time += datetime.timedelta(seconds=seconds)

    class datetime:
        @classmethod
        def utcnow(cls):
            return MockDatetime.current_time

        @classmethod
        def strptime(cls, date_string, format_string):
            return datetime.datetime.strptime(date_string, format_string)

        @classmethod
        def now(cls, tz=None):
            return MockDatetime.current_time


class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        # Setup paths
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        # Backup existing data if any
        self.backup_folder = os.path.join(self.project_root, 'data_backup')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        # Ensure clean state for test
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Initialize empty structured ledger
        with open(self.ledger_path, 'w') as f:
            json.dump({
                "ledger": {},
                "system_state": {
                    "core_heat": 0.0,
                    "last_processed_timestamp": "2025-06-15T12:00:00Z"
                }
            }, f)

        # Reset MockDatetime
        MockDatetime.set_time(datetime.datetime(2025, 6, 15, 12, 0, 0))

        # Patch datetime module inside utils.dna_ui
        self.patcher = patch('utils.dna_ui.datetime', MockDatetime)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        # Restore backup
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            if os.path.exists(self.backup_folder):
                shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation_and_decay(self):
        """Verify that successfully parsed sequences accumulate heat and dissipate over time."""
        # 1. Process 1 valid sequence (adds 2.0 heat units)
        with open(self.input_file, 'w') as f:
            f.write("VOL08900750712\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)

        self.assertIn("system_state", data)
        self.assertEqual(data["system_state"]["core_heat"], 2.0)

        # 2. Advance time by 2.0 seconds -> should decay 2.0 * 0.5 = 1.0 unit of heat
        MockDatetime.advance_seconds(2)

        with open(self.input_file, 'w') as f:
            f.write("VOL00000000000\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)

        # Heat before processing = max(0, 2.0 - 1.0) = 1.0
        # Processing S2 (success) adds 2.0 -> final heat = 3.0
        self.assertEqual(data["system_state"]["core_heat"], 3.0)

    def test_thermal_lockout_threshold(self):
        """Verify that heat threshold of 10.0 triggers lockout, refusing further runs."""
        # 5 successful parses (5 * 2.0 = 10.0 heat units)
        dna_seqs = [
            "VOL08900750712",
            "VOL00000000000",
            "VOL08900750713",
            "VOL08900750714",
            "VOL08900750715",
            "VOL08900750716" # This 6th one should lockout since heat is now 10.0
        ]

        with open(self.input_file, 'w') as f:
            for s in dna_seqs:
                f.write(s + "\n")

        # Running batch processing should raise ThermalOverloadError
        with self.assertRaises(ThermalOverloadError) as context:
            run_batch()

        self.assertIn(UI_FEEDBACK["refusal_reason"], str(context.exception))
        self.assertIn(UI_FEEDBACK["next_action_hint"], str(context.exception))

        # Check ledger
        with open(self.ledger_path, 'r') as f:
            data = json.load(f)

        ledger = data["ledger"]
        # First 5 should be success
        for s in dna_seqs[:5]:
            self.assertEqual(ledger[s]["terminal_outcome"], "success")

        # 6th should be refused
        self.assertEqual(ledger[dna_seqs[5]]["terminal_outcome"], "refused")
        self.assertEqual(data["system_state"]["core_heat"], 10.0)

    def test_idempotency_does_not_add_heat(self):
        """Verify that skipping already processed terminal sequences does not add unnecessary heat."""
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch() # 1st run: success, core_heat = 2.0

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data["system_state"]["core_heat"], 2.0)

        # 2nd run with same DNA sequence immediately
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch() # 2nd run: skipped

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)

        # Heat should not have increased because it was skipped!
        self.assertEqual(data["system_state"]["core_heat"], 2.0)


if __name__ == '__main__':
    unittest.main()
