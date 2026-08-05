import os
import json
import shutil
import unittest
import datetime
from unittest.mock import patch, MagicMock
from utils.dna_ui import main as run_batch, ThermalOverloadError, DNAProcessingError

# Deterministic Mock for Datetime
class MockDatetime:
    timezone = datetime.timezone
    _now = datetime.datetime(2025, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

    class datetime:
        @classmethod
        def now(cls, tz=None):
            return MockDatetime._now

        @classmethod
        def strptime(cls, date_string, format_string):
            return datetime.datetime.strptime(date_string, format_string)

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
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

        # Initialize clean ledger
        with open(self.ledger_path, 'w') as f:
            json.dump({
                "system_status": {
                    "current_heat": 0.0,
                    "last_update": None
                },
                "ledger": {}
            }, f)

        # Start with default mock time
        MockDatetime._now = datetime.datetime(2025, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

    def tearDown(self):
        # Restore backup
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_accumulation(self):
        # Write 3 valid DNA sequences (e.g. VOL prefix is valid)
        with open(self.input_file, 'w') as f:
            f.write("VOL01002003004\nVOL02002003004\nVOL03002003004\n")

        run_batch()

        # Check heat in ledger (3 successful sequences * 2.0 heat = 6.0)
        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)

        current_heat = ledger["system_status"]["current_heat"]
        self.assertAlmostEqual(current_heat, 6.0)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_dissipation(self):
        # Run 1 sequence
        with open(self.input_file, 'w') as f:
            f.write("VOL01002003004\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertAlmostEqual(ledger["system_status"]["current_heat"], 2.0)

        # Mock time forward by 2 seconds. Cools at 0.5/sec, so 1.0 heat dissipated.
        MockDatetime._now += datetime.timedelta(seconds=2)

        # Run 2nd sequence
        with open(self.input_file, 'w') as f:
            f.write("VOL02002003004\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)

        # 2.0 heat - 1.0 dissipated + 2.0 new heat = 3.0 heat
        self.assertAlmostEqual(ledger["system_status"]["current_heat"], 3.0)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_thermal_lockout_and_partial_commits(self):
        # Write 6 valid sequences (needs 5 to reach 10.0 heat, 6th should cause lockout)
        sequences = [f"VOL0{i}002003004" for i in range(1, 7)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        # Expect ThermalOverloadError due to the 6th sequence triggering lockout
        with self.assertRaises(ThermalOverloadError) as context:
            run_batch()

        self.assertIn("Thermal Lockout", str(context.exception))
        self.assertIn("Wait for dissipation. The system is indifferent to your deadlines.", str(context.exception))

        # Check ledger status - heat should be 10.0
        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertAlmostEqual(ledger["system_status"]["current_heat"], 10.0)

        # Exactly 5 should be committed
        ledger_entries = ledger["ledger"]
        self.assertEqual(len(ledger_entries), 5)
        for i in range(1, 6):
            self.assertIn(f"VOL0{i}002003004", ledger_entries)
        self.assertNotIn("VOL06002003004", ledger_entries)

        # Check output JSON has exactly 5 entries
        with open(self.json_output, 'r') as f:
            json_data = json.load(f)
        self.assertEqual(len(json_data), 5)

if __name__ == '__main__':
    unittest.main()
