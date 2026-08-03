import sys
from unittest.mock import MagicMock

# Mock GUI/audio dependencies for headless environments
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
import json
import shutil
import tempfile
import time
from unittest.mock import patch
import datetime as real_datetime

# Define Mock Datetime
BASE_TIME = real_datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc)
current_mock_time = BASE_TIME

class MockDatetimeClass:
    @classmethod
    def now(cls, tz=None):
        return current_mock_time
    @classmethod
    def strptime(cls, date_string, format_string):
        return real_datetime.datetime.strptime(date_string, format_string)

class MockDatetimeModule:
    datetime = MockDatetimeClass
    timezone = real_datetime.timezone

from utils.dna_ui import run_batch, ThermalOverloadError, DNAStatus, load_ledger, save_ledger

class TestFatigue(unittest.TestCase):
    def setUp(self):
        global current_mock_time
        current_mock_time = BASE_TIME

        # Patch datetime module in dna_ui
        self.patcher = patch('utils.dna_ui.datetime', MockDatetimeModule)
        self.patcher.start()

        # Create a temporary project structure
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

        # Mock a rule file for 'Volume' (V prefix)
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "V",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        self.patcher.stop()
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation(self):
        """Verify that each successful DNA parse adds 2.0 heat units."""
        # 3 DNA sequences -> should add 6.0 heat units
        with open(self.input_file, 'w') as f:
            f.write("V100\nV200\nV300\n")

        run_batch()

        # Check ledger
        ledger = load_ledger(self.ledger_path)
        system_heat = ledger.get('system_heat', 0.0)
        self.assertAlmostEqual(system_heat, 6.0, places=2)

    def test_heat_dissipation(self):
        """Verify that heat dissipates over time at 0.5 units/second."""
        global current_mock_time
        # Set mock time to base time
        current_mock_time = BASE_TIME

        # Setup ledger with pre-existing heat of 8.0
        ledger = {
            "system_heat": 8.0,
            "_system_heat": 8.0,
            "last_processed_timestamp": current_mock_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
            "_last_processed_timestamp": current_mock_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
            "ledger": {}
        }
        save_ledger(self.ledger_path, ledger)

        # Advance mock time by 10 seconds -> should dissipate 10 * 0.5 = 5.0 heat, bringing it down to 3.0,
        # then add 2.0 heat for processing the sequence, resulting in 5.0 heat.
        current_mock_time = BASE_TIME + real_datetime.timedelta(seconds=10)

        with open(self.input_file, 'w') as f:
            f.write("V100\n")

        run_batch()

        updated_ledger = load_ledger(self.ledger_path)
        updated_heat = updated_ledger.get('system_heat', 0.0)
        self.assertAlmostEqual(updated_heat, 5.0, places=2)

    def test_thermal_lockout_and_partial_commitment(self):
        """
        Verify that:
        1. If heat reaches/exceeds 10.0, ThermalOverloadError is raised (lockout).
        2. Processed items before lockout are committed to outputs and ledger.
        3. Remaining items are NOT marked as processed (no silent drains).
        """
        global current_mock_time
        current_mock_time = BASE_TIME

        # Start with heat at 8.0
        ledger = {
            "system_heat": 8.0,
            "_system_heat": 8.0,
            "last_processed_timestamp": current_mock_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
            "_last_processed_timestamp": current_mock_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
            "ledger": {}
        }
        save_ledger(self.ledger_path, ledger)

        # Write 3 sequences:
        # V100: processes successfully, heat goes to 10.0
        # V200: blocked by lockout (system_heat >= 10.0)
        # V300: not processed
        with open(self.input_file, 'w') as f:
            f.write("V100\nV200\nV300\n")

        with self.assertRaises(ThermalOverloadError) as context:
            run_batch()

        self.assertIn("Thermal Lockout: safety heat threshold exceeded", str(context.exception))

        # Check ledger and output files for partial commitment
        updated_ledger = load_ledger(self.ledger_path)

        # V100 must be in ledger and marked successful
        sub_ledger = updated_ledger.get('ledger', updated_ledger)
        self.assertIn("V100", sub_ledger)
        self.assertEqual(sub_ledger["V100"]["terminal_outcome"], "success")

        # V200 and V300 must NOT be in ledger
        self.assertNotIn("V200", sub_ledger)
        self.assertNotIn("V300", sub_ledger)

        # Heat should be committed as 10.0
        self.assertAlmostEqual(updated_ledger.get('system_heat', 0.0), 10.0, places=2)

        # Outputs must be updated atomically with V100 only
        json_out_path = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertTrue(os.path.exists(json_out_path))
        with open(json_out_path, 'r') as jf:
            parsed_data = json.load(jf)
        self.assertEqual(len(parsed_data), 1)
        self.assertEqual(parsed_data[0]["dna"], "V100")

    def test_idle_cooling_cycles(self):
        """Verify that batch processor persists updated system heat even if 0 new sequences are processed."""
        global current_mock_time
        current_mock_time = BASE_TIME

        ledger = {
            "system_heat": 8.0,
            "_system_heat": 8.0,
            "last_processed_timestamp": current_mock_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
            "_last_processed_timestamp": current_mock_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
            "ledger": {
                "V100": {"terminal_outcome": "success", "timestamp": current_mock_time.strftime('%Y-%m-%dT%H:%M:%SZ')}
            }
        }
        save_ledger(self.ledger_path, ledger)

        # Advance mock time by 10 seconds -> should dissipate 10 * 0.5 = 5.0 heat, bringing it down to 3.0.
        current_mock_time = BASE_TIME + real_datetime.timedelta(seconds=10)

        # Write duplicate/already-processed DNA so 0 new items are processed
        with open(self.input_file, 'w') as f:
            f.write("V100\n")

        run_batch()

        # Check that heat decreased to 3.0 (8.0 - 10 * 0.5) and was recorded
        updated_ledger = load_ledger(self.ledger_path)
        updated_heat = updated_ledger.get('system_heat', 0.0)
        self.assertAlmostEqual(updated_heat, 3.0, places=2)

if __name__ == '__main__':
    unittest.main()
