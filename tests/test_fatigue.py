import sys
from unittest.mock import MagicMock

# Mock dependencies before any imports
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
import datetime
from unittest.mock import patch

from utils.dna_ui import run_batch, ThermalOverloadError, MAX_HEAT, HEAT_PER_SEQ, COOLING_RATE

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
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

        # Mock a rule file for Volume
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
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation_per_sequence(self):
        """Assert that heat accumulates correctly per parsed sequence."""
        # Write 2 DNA sequences to parse
        with open(self.input_file, 'w') as f:
            f.write("V100\nV200\n")

        run_batch()

        # Check the ledger state
        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # Expected heat is 2 sequences * HEAT_PER_SEQ = 40.0
        # Account for any small cooling due to elapsed time if tests are not mocked
        # But since we run sequentially and immediately, it should be close to 40.0.
        self.assertGreaterEqual(state["system_heat"], 35.0)
        self.assertLessEqual(state["system_heat"], 40.0)

    def test_heat_dissipation_over_time(self):
        """Assert that heat dissipates over time according to COOLING_RATE."""
        # Initialize ledger with some heat and a past timestamp
        past_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=10)
        state = {
            "system_heat": 50.0,
            "last_processed_timestamp": past_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
            "ledger": {}
        }
        with open(self.ledger_path, 'w') as f:
            json.dump(state, f, indent=2)

        # Run batch with no new inputs (idle run) to trigger dissipation
        with open(self.input_file, 'w') as f:
            f.write("")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            updated_state = json.load(f)

        # Dissipated heat should be: 50.0 - 10 * COOLING_RATE = 30.0 (non-strict check to allow slight delta)
        self.assertLessEqual(updated_state["system_heat"], 35.0)

    def test_thermal_lockout_refusal(self):
        """Assert that further processing is refused once MAX_HEAT is reached/exceeded."""
        # Set heat safely above MAX_HEAT directly so tiny dissipation doesn't lower it below threshold
        state = {
            "system_heat": MAX_HEAT + 10.0,
            "last_processed_timestamp": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            "ledger": {}
        }
        with open(self.ledger_path, 'w') as f:
            json.dump(state, f, indent=2)

        with open(self.input_file, 'w') as f:
            f.write("V100\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            updated_state = json.load(f)

        # Ensure the sequence was marked as 'refused' in the ledger
        self.assertEqual(updated_state["ledger"]["V100"]["terminal_outcome"], "refused")

    def test_idempotency_no_extra_heat(self):
        """Assert that reprocessing a known terminal sequence does not add heat."""
        # Initialize ledger with V100 already processed
        state = {
            "system_heat": 30.0,
            "last_processed_timestamp": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            "ledger": {
                "V100": {
                    "terminal_outcome": "success",
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                }
            }
        }
        with open(self.ledger_path, 'w') as f:
            json.dump(state, f, indent=2)

        with open(self.input_file, 'w') as f:
            f.write("V100\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            updated_state = json.load(f)

        # Heat should be less than or equal to 30.0 (cooling occurs, no new heat added)
        self.assertLessEqual(updated_state["system_heat"], 30.0)

    def test_no_silent_drains_under_overload(self):
        """Verify that under lockout, the exception is propagated to main.py watcher, ensuring file is NOT cleared."""
        # We simulate main.py behavior on ThermalOverloadError
        if 'main' in sys.modules:
            del sys.modules['main']
        import main

        # Set heat to lockout threshold
        state = {
            "system_heat": MAX_HEAT + 10.0,
            "last_processed_timestamp": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            "ledger": {}
        }
        with open(self.ledger_path, 'w') as f:
            json.dump(state, f, indent=2)

        with open(self.input_file, 'w') as f:
            f.write("V100\n")

        # Running process_once() should exit with code 1 instead of silent drain
        # Patch main.__file__ so that paths are resolved relative to self.test_dir
        with patch('main.__file__', os.path.join(self.test_dir, 'main.py')):
            with patch('main.sys.exit') as mock_exit:
                main.process_once()
                mock_exit.assert_called_with(1)

        # The input file must NOT be cleared, so "V100" remains
        with open(self.input_file, 'r') as f:
            content = f.read().strip()
        self.assertEqual(content, "V100")

if __name__ == '__main__':
    unittest.main()
