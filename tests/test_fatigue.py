import unittest
import os
import shutil
import tempfile
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

# Mock PySide6 if needed before imports
mock_pyside6 = MagicMock()
import sys
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

from utils.dna_ui import (
    main as run_batch,
    ThermalOverloadError,
    UI_MESSAGES,
    LOCKOUT_THRESHOLD,
    HEAT_PER_SEQUENCE,
    COOLING_RATE_PER_SEC
)

class MockDatetime:
    current_time = datetime(2026, 1, 1, 12, 0, 0)

    @classmethod
    def now(cls, tz=None):
        return cls.current_time

    @classmethod
    def strptime(cls, date_string, format_string):
        return datetime.strptime(date_string, format_string)

class TestThermalFatigue(unittest.TestCase):
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
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')

        # Mock rule file for prefix VOL
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

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_thermal_fatigue_and_lockout_and_no_silent_drains(self):
        MockDatetime.current_time = datetime(2026, 1, 1, 12, 0, 0)

        # Write 6 unique sequences (each adds 2.0 heat; threshold is 10.0 heat -> 5th sequence reaches 10.0 heat, 6th triggers lockout)
        sequences = [f"VOL{i:03d}00000000" for i in range(1, 7)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        with patch('utils.dna_ui.datetime', MockDatetime):
            with self.assertRaises(ThermalOverloadError) as ctx:
                run_batch()

            err_msg = str(ctx.exception)
            self.assertIn(UI_MESSAGES["refusal_reason"], err_msg)

            # Check ledger state: 5 sequences processed (heat reached 10.0), 6th refused
            with open(self.ledger_file, 'r') as f:
                ledger_data = json.load(f)

            processed_ledger = ledger_data.get('ledger', {})
            system_state = ledger_data.get('system_state', {})

            self.assertEqual(len(processed_ledger), 5, "Exactly 5 sequences should have been processed before lockout.")
            self.assertEqual(system_state.get('core_heat'), 10.0)

            # Idempotency / No silent drains check:
            # Re-running immediately must be refused at startup without processing any additional sequences or draining heat silently.
            with open(self.input_file, 'w') as f:
                f.write("VOL99900000000\n")

            with self.assertRaises(ThermalOverloadError):
                run_batch()

            # Verify ledger was untouched during refused run
            with open(self.ledger_file, 'r') as f:
                ledger_data_after = json.load(f)

            self.assertEqual(len(ledger_data_after.get('ledger', {})), 5)
            self.assertEqual(ledger_data_after.get('system_state', {}).get('core_heat'), 10.0)

    def test_thermal_dissipation_allows_recovery(self):
        MockDatetime.current_time = datetime(2026, 1, 1, 12, 0, 0)

        # 1. Heat up system to 10.0 heat
        sequences = [f"VOL{i:03d}00000000" for i in range(1, 6)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        with patch('utils.dna_ui.datetime', MockDatetime):
            run_batch()

            with open(self.ledger_file, 'r') as f:
                ledger_data = json.load(f)
            self.assertEqual(ledger_data['system_state']['core_heat'], 10.0)

            # 2. Advance time by 10 seconds (10s * 0.5 heat/s = 5.0 heat dissipated -> remaining heat = 5.0)
            MockDatetime.current_time = datetime(2026, 1, 1, 12, 0, 10)

            with open(self.input_file, 'w') as f:
                f.write("VOL10000000000\n")

            run_batch()

            with open(self.ledger_file, 'r') as f:
                ledger_data_after = json.load(f)

            # Core heat was 5.0 after dissipation + 2.0 added for new sequence = 7.0
            self.assertEqual(ledger_data_after['system_state']['core_heat'], 7.0)
            self.assertIn("VOL10000000000", ledger_data_after['ledger'])

if __name__ == '__main__':
    unittest.main()
