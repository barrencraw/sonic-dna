import sys
from unittest.mock import MagicMock, patch

# Mock PySide6 and other modules to avoid dependency issues on headless CI
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

import unittest
import os
import shutil
import tempfile
import json
import datetime as real_datetime
from utils.dna_ui import run_batch, ThermalOverloadError, DNAStatus, load_ledger, save_ledger

class MockDatetimeClass:
    @classmethod
    def now(cls, tz=None):
        return TestFatigue.current_mock_time

    @classmethod
    def strptime(cls, date_string, format_str):
        return real_datetime.datetime.strptime(date_string, format_str)

class MockDatetimeModule:
    datetime = MockDatetimeClass
    timezone = real_datetime.timezone

class TestFatigue(unittest.TestCase):
    current_mock_time = real_datetime.datetime(2025, 6, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc)

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')

        # Mock a rule file for Volume ('V')
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w', encoding='utf-8') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "V",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Reset current mock time
        TestFatigue.current_mock_time = real_datetime.datetime(2025, 6, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc)

        # Patch 'datetime' module in utils.dna_ui
        self.patcher = patch('utils.dna_ui.datetime', MockDatetimeModule)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation_per_sequence(self):
        """Test that heat accumulates by 2.0 units per processed sequence."""
        # Write 3 valid sequences to file
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("V100\nV200\nV300\n")

        run_batch()

        # Check heat in ledger
        ledger = load_ledger(self.ledger_path)
        self.assertAlmostEqual(ledger.get('system_heat', 0.0), 6.0)

    def test_lockout_triggered_and_intermediate_commit(self):
        """Test that safety limit (10.0) lockout triggers, raising ThermalOverloadError,
        committing parsed sequences before lockout, and writing refused entries."""
        # Write 6 valid sequences to file (each is 2.0 heat, total would be 12.0)
        # 5th sequence will bring heat to 10.0, 6th will be refused.
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("V100\nV200\nV300\nV400\nV500\nV600\n")

        # Running batch should raise ThermalOverloadError
        with self.assertRaises(ThermalOverloadError) as context:
            run_batch()

        # Verify error message and properties contain the legibility keys
        err = context.exception
        self.assertEqual(err.message, "Thermal Lockout")
        self.assertEqual(err.consequence, "Heat Accumulation")
        self.assertEqual(err.hint, "Wait for dissipation. The system is indifferent to your deadlines.")

        # Load ledger to verify state
        ledger = load_ledger(self.ledger_path)
        self.assertAlmostEqual(ledger.get('system_heat', 0.0), 10.0)

        # Verify outcomes in ledger
        self.assertEqual(ledger.get('V100', {}).get('terminal_outcome'), 'success')
        self.assertEqual(ledger.get('V200', {}).get('terminal_outcome'), 'success')
        self.assertEqual(ledger.get('V300', {}).get('terminal_outcome'), 'success')
        self.assertEqual(ledger.get('V400', {}).get('terminal_outcome'), 'success')
        self.assertEqual(ledger.get('V500', {}).get('terminal_outcome'), 'success')
        self.assertEqual(ledger.get('V600', {}).get('terminal_outcome'), 'refused')

        # Check JSON output file has 5 successfully parsed entries
        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r', encoding='utf-8') as f:
            parsed = json.load(f)
        # V100, V200, V300, V400, V500 are successfully parsed. V600 was refused before parsing.
        self.assertEqual(len(parsed), 5)
        self.assertEqual(parsed[0]['dna'], 'V100')

    def test_heat_dissipation_over_time(self):
        """Test that heat dissipates at 0.5 units per second over time."""
        # Step 1: Accumulate heat to 6.0
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("V100\nV200\nV300\n")
        run_batch()

        ledger = load_ledger(self.ledger_path)
        self.assertAlmostEqual(ledger.get('system_heat', 0.0), 6.0)

        # Step 2: Simulate passage of 4 seconds (4 * 0.5 = 2.0 heat dissipation)
        TestFatigue.current_mock_time += real_datetime.timedelta(seconds=4)

        # Run an idle/empty batch to register dissipation
        # Overwrite the input file to be empty
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("")

        run_batch()

        # Check ledger after dissipation
        ledger2 = load_ledger(self.ledger_path)
        self.assertAlmostEqual(ledger2.get('system_heat', 0.0), 4.0)

    def test_idempotency_avoids_heat(self):
        """Test that already processed sequences are skipped and do not generate heat."""
        # Process V100 first
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("V100\n")
        run_batch()

        ledger = load_ledger(self.ledger_path)
        self.assertAlmostEqual(ledger.get('system_heat', 0.0), 2.0)

        # Process V100 again (no time elapsed)
        # It should hit dedupe and NOT generate heat
        run_batch()

        ledger2 = load_ledger(self.ledger_path)
        self.assertAlmostEqual(ledger2.get('system_heat', 0.0), 2.0)

if __name__ == '__main__':
    unittest.main()
