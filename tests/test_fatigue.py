import sys
from unittest.mock import MagicMock

# Mock GUI dependencies before imports
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

import os
import shutil
import tempfile
import json
import unittest
import datetime
from unittest.mock import patch
from utils.dna_ui import run_batch, ThermalOverloadError, DNAStatus

class MockDatetime:
    timezone = datetime.timezone
    _now_val = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

    class datetime:
        @classmethod
        def now(cls, tz=None):
            return MockDatetime._now_val

        @classmethod
        def strptime(cls, date_string, format_string):
            return datetime.datetime.strptime(date_string, format_string)

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

        # Mock Volume rule
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

        # Set initial time
        MockDatetime._now_val = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    @patch('utils.dna_ui.datetime', new=MockDatetime)
    def test_heat_accumulation(self):
        """Verify that successful sequences accumulate heat (2.0 per sequence)."""
        # We write 3 valid DNA lines
        with open(self.input_file, 'w') as f:
            f.write("V100\nV200\nV300\n")

        run_batch()

        # Check ledger
        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)

        self.assertIn('system_state', ledger_data)
        # 3 successfully parsed sequences -> 3 * 2.0 = 6.0 heat
        self.assertEqual(ledger_data['system_state']['core_heat'], 6.0)

    @patch('utils.dna_ui.datetime', new=MockDatetime)
    def test_thermal_decay(self):
        """Verify that thermal heat decays by 0.5 per second over elapsed time."""
        # Setup pre-existing heat of 6.0 in ledger at 12:00:00
        initial_time_str = "2026-03-02T12:00:00Z"
        initial_ledger = {
            'ledger': {
                'V100': {'terminal_outcome': 'success', 'timestamp': '2026-03-02 12:00:00'}
            },
            'system_state': {
                'core_heat': 6.0,
                'last_processed_timestamp': initial_time_str
            }
        }
        with open(self.ledger_file, 'w') as f:
            json.dump(initial_ledger, f, indent=2)

        # Simulate 4 seconds passing (4 * 0.5 = 2.0 units of decay)
        # Initial: 6.0, Decay: 2.0 -> Base core_heat before sequence should be 4.0.
        # Adding one successful sequence (V200) -> adds 2.0 units -> New core_heat should be 6.0.
        MockDatetime._now_val = datetime.datetime(2026, 3, 2, 12, 0, 4, tzinfo=datetime.timezone.utc)

        with open(self.input_file, 'w') as f:
            f.write("V200\n")

        run_batch()

        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)

        self.assertEqual(ledger_data['system_state']['core_heat'], 6.0)

    @patch('utils.dna_ui.datetime', new=MockDatetime)
    def test_thermal_lockout_trigger(self):
        """Verify that exceeding 10.0 heat units triggers ThermalOverloadError and refuses processing."""
        # Setup initial state with 10.0 heat units (exactly at lockout threshold)
        initial_time_str = "2026-03-02T12:00:00Z"
        initial_ledger = {
            'ledger': {
                'V100': {'terminal_outcome': 'success', 'timestamp': '2026-03-02 12:00:00'}
            },
            'system_state': {
                'core_heat': 10.0,
                'last_processed_timestamp': initial_time_str
            }
        }
        with open(self.ledger_file, 'w') as f:
            json.dump(initial_ledger, f, indent=2)

        # No time passes, so core_heat is still 10.0
        with open(self.input_file, 'w') as f:
            f.write("V200\n")

        with self.assertRaises(ThermalOverloadError) as context:
            run_batch()

        self.assertIn("Thermal Lockout", str(context.exception))
        self.assertIn("The system is indifferent to your deadlines.", str(context.exception))

        # Output JSON and CSV should NOT have been updated (no silent drains)
        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertFalse(os.path.exists(json_out))

    @patch('utils.dna_ui.datetime', new=MockDatetime)
    def test_thermal_recovery(self):
        """Verify that waiting long enough allows recovery from lockout via decay."""
        # Setup initial state with 10.0 heat units
        initial_time_str = "2026-03-02T12:00:00Z"
        initial_ledger = {
            'ledger': {
                'V100': {'terminal_outcome': 'success', 'timestamp': '2026-03-02 12:00:00'}
            },
            'system_state': {
                'core_heat': 10.0,
                'last_processed_timestamp': initial_time_str
            }
        }
        with open(self.ledger_file, 'w') as f:
            json.dump(initial_ledger, f, indent=2)

        # Let 22 seconds pass.
        # 22 seconds * 0.5 decay/sec = 11.0 heat decay -> core_heat becomes 0.0.
        MockDatetime._now_val = datetime.datetime(2026, 3, 2, 12, 0, 22, tzinfo=datetime.timezone.utc)

        with open(self.input_file, 'w') as f:
            f.write("V200\n")

        # This should execute successfully and not raise ThermalOverloadError
        run_batch()

        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)

        # Decayed to 0.0, then V200 succeeded (adds 2.0) -> New core_heat should be 2.0.
        self.assertEqual(ledger_data['system_state']['core_heat'], 2.0)
