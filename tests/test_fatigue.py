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
from unittest.mock import patch
import datetime

from utils.dna_ui import main as run_batch, ThermalOverloadError, DNAProcessingError

class MockDatetime:
    timezone = datetime.timezone

    class datetime:
        _now = datetime.datetime(2026, 3, 31, 12, 0, 0, tzinfo=datetime.timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls._now

        @classmethod
        def strptime(cls, date_string, format_string):
            return datetime.datetime.strptime(date_string, format_string)

        @classmethod
        def set_now(cls, dt):
            cls._now = dt

        @classmethod
        def advance(cls, seconds):
            cls._now += datetime.timedelta(seconds=seconds)

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
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')

        # Mock rule file for Volume (total length 6: 'VOL' + 3-digit level)
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Reset MockDatetime
        MockDatetime.datetime.set_now(datetime.datetime(2026, 3, 31, 12, 0, 0, tzinfo=datetime.timezone.utc))

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_accumulation(self):
        """Verify that successful parses add 2.0 heat units."""
        # Process first sequence
        with open(self.input_file, 'w') as f:
            f.write("VOL100\n")
        run_batch()

        # Check ledger
        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)

        self.assertIn("system_state", ledger_data)
        self.assertEqual(ledger_data["system_state"]["core_heat"], 2.0)

        # Process second sequence
        with open(self.input_file, 'w') as f:
            f.write("VOL200\n")
        run_batch()

        # Check ledger again
        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)

        self.assertEqual(ledger_data["system_state"]["core_heat"], 4.0)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_dissipation(self):
        """Verify that heat cools down at a rate of 0.5 units per second."""
        # Process first sequence. Heat becomes 2.0.
        with open(self.input_file, 'w') as f:
            f.write("VOL100\n")
        run_batch()

        # Advance simulated time by 2 seconds. Heat should decay by 2 * 0.5 = 1.0.
        MockDatetime.datetime.advance(2)

        # Process second sequence. Heat decays to 1.0, then increases by 2.0 -> 3.0.
        with open(self.input_file, 'w') as f:
            f.write("VOL200\n")
        run_batch()

        # Check ledger
        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)

        self.assertEqual(ledger_data["system_state"]["core_heat"], 3.0)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_lockout_behavior(self):
        """Verify that reaching 10.0 heat triggers a lockout exception and refuses further work."""
        # Write 5 valid sequences to reach 10.0 heat
        with open(self.input_file, 'w') as f:
            for i in range(5):
                f.write(f"VOL10{i}\n")
        run_batch()

        # Verify heat is 10.0
        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)
        self.assertEqual(ledger_data["system_state"]["core_heat"], 10.0)

        # Attempting to process another sequence should trigger ThermalOverloadError
        with open(self.input_file, 'w') as f:
            f.write("VOL200\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # The refused sequence should be marked as "refused" in the ledger
        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)
        self.assertEqual(ledger_data["ledger"]["VOL200"]["terminal_outcome"], "refused")

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_idempotency_no_silent_drains(self):
        """Verify skipped sequences do not add heat and do not rewrite outputs unnecessarily."""
        # Process first sequence. Heat becomes 2.0.
        with open(self.input_file, 'w') as f:
            f.write("VOL100\n")
        run_batch()

        # Get initial output timestamps/content
        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        mtime_before = os.path.getmtime(json_out)

        # Try to process the same sequence again
        with open(self.input_file, 'w') as f:
            f.write("VOL100\n")
        run_batch()

        # Heat should NOT have increased
        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)
        self.assertEqual(ledger_data["system_state"]["core_heat"], 2.0)

        # Output files should not have been touched
        mtime_after = os.path.getmtime(json_out)
        self.assertEqual(mtime_before, mtime_after, "Output files should not have been rewritten for zero new processed sequences.")

if __name__ == '__main__':
    unittest.main()
