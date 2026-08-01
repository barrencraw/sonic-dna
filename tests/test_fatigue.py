import os
import json
import shutil
import unittest
import datetime
from unittest.mock import patch, MagicMock
from utils.dna_ui import run_batch, ThermalOverloadError, CoreExhaustionError, load_ledger

class MockDatetime:
    timezone = datetime.timezone
    class datetime:
        _now = datetime.datetime(2025, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls._now

        @classmethod
        def strptime(cls, date_string, format_string):
            return datetime.datetime.strptime(date_string, format_string)

class TestThermalFatigueAndDebt(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        # Backup existing data if any
        self.backup_folder = os.path.join(self.project_root, 'data_backup')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        # Clean slate
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Initialize empty ledger
        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)

        # Reset Mock Datetime
        MockDatetime.datetime._now = datetime.datetime(2025, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

    def tearDown(self):
        # Restore backup
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            if os.path.exists(self.backup_folder):
                shutil.move(self.backup_folder, self.data_folder)

    @patch('utils.dna_ui.datetime', new=MockDatetime)
    def test_heat_accumulation_per_sequence(self):
        # Each successfully parsed sequence adds 2.0 heat units
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        ledger = load_ledger(self.ledger_path)
        heat = ledger.get('system_heat', 0.0)
        # Non-strict comparison to support time-based cooling or exact match
        self.assertTrue(heat >= 1.9, f"Heat should accumulate to approximately 2.0, got {heat}")

    @patch('utils.dna_ui.datetime', new=MockDatetime)
    def test_heat_dissipation_over_time(self):
        # 1. Parse one sequence to generate 2.0 heat
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")
        run_batch()

        # Verify heat is around 2.0
        ledger = load_ledger(self.ledger_path)
        self.assertTrue(ledger.get('system_heat', 0.0) >= 1.9)

        # 2. Advance time by 2 seconds (mainframe cools down at 0.5 heat units per second, so should dissipate 1.0 heat)
        MockDatetime.datetime._now += datetime.timedelta(seconds=2)

        # Run batch again with another DNA (to trigger dissipation/update)
        dna2 = "VOL00000000000"
        with open(self.input_file, 'w') as f:
            f.write(dna2 + "\n")
        run_batch()

        # Ledger should have recorded the dissipation: 2.0 - 1.0 (cooling) + 2.0 (new parse) = 3.0 heat
        ledger = load_ledger(self.ledger_path)
        heat = ledger.get('system_heat', 0.0)
        self.assertTrue(heat >= 2.9 and heat <= 3.1, f"Expected heat around 3.0 after dissipation and new parsing, got {heat}")

    @patch('utils.dna_ui.datetime', new=MockDatetime)
    def test_thermal_lockout_after_threshold(self):
        # Lockout safety threshold is 10.0 heat units.
        # Parse 5 sequences. Each successfully parsed sequence adds 2.0 heat units.
        # 5 * 2.0 = 10.0 heat.
        # The 6th sequence should trigger ThermalOverloadError.
        sequences = [
            "VOL08900750712",
            "VOL00000000000",
            "VOL00000000001",
            "VOL00000000002",
            "VOL00000000003",
            "VOL00000000004"
        ]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # Verify items processed BEFORE the lockout are committed to the output files and ledger
        ledger = load_ledger(self.ledger_path)
        seq_ledger = ledger.get('ledger', ledger)
        # Should have successfully processed 5 sequences
        processed_count = sum(1 for s in sequences if s in seq_ledger and seq_ledger[s]['terminal_outcome'] == 'success')
        self.assertEqual(processed_count, 5, "Exactly 5 sequences should have been processed and saved before lockout")

    @patch('utils.dna_ui.datetime', new=MockDatetime)
    def test_thermal_debt_lowers_safety_threshold(self):
        # Including 'FORCE_OVERRIDE' in the input file adds 2.0 system debt, which lowers threshold to 8.0.
        # Then, parsing 4 sequences will add 4 * 2.0 = 8.0 heat.
        # The 5th sequence should trigger ThermalOverloadError since the threshold is now 8.0 instead of 10.0.
        sequences = [
            "FORCE_OVERRIDE",
            "VOL08900750712",
            "VOL00000000000",
            "VOL00000000001",
            "VOL00000000002",
            "VOL00000000003"
        ]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # Verify that exactly 4 sequences were processed before the lowered lockout (at 8.0 heat)
        ledger = load_ledger(self.ledger_path)
        self.assertEqual(ledger.get('system_debt', 0.0), 2.0)
        seq_ledger = ledger.get('ledger', ledger)
        processed_count = sum(1 for s in sequences if s in seq_ledger and seq_ledger[s]['terminal_outcome'] == 'success')
        self.assertEqual(processed_count, 4)

    @patch('utils.dna_ui.datetime', new=MockDatetime)
    def test_core_exhaustion_at_max_debt(self):
        # 5 FORCE_OVERRIDE lines in input file = 10.0 system debt.
        # This should trigger CoreExhaustionError and refuse all further operations.
        sequences = [
            "FORCE_OVERRIDE",
            "FORCE_OVERRIDE",
            "FORCE_OVERRIDE",
            "FORCE_OVERRIDE",
            "FORCE_OVERRIDE"
        ]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        with self.assertRaises(CoreExhaustionError):
            run_batch()

        # Verify system debt is persisted at 10.0
        ledger = load_ledger(self.ledger_path)
        self.assertEqual(ledger.get('system_debt', 0.0), 10.0)

if __name__ == '__main__':
    unittest.main()
