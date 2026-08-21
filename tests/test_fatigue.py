import sys
from unittest.mock import MagicMock

# Mock GUI dependencies before any imports
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

from utils.dna_ui import (
    run_batch,
    ThermalOverloadError,
    CONSEQUENCE_APPLIED,
    REFUSAL_REASON,
    NEXT_ACTION_HINT
)

class MockDatetimeModule:
    current_time = datetime.datetime(2025, 6, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)
    timezone = datetime.timezone

    class datetime:
        @classmethod
        def now(cls, tz=None):
            return MockDatetimeModule.current_time

        @classmethod
        def strptime(cls, date_string, format_string):
            return datetime.datetime.strptime(date_string, format_string)

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
        self.ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')

        # Mock a Volume rule file
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w', encoding='utf-8') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3},
                    "pan": {"description": "panning", "min": 0, "max": 999, "pad": 3},
                    "fade_in": {"description": "fade in", "min": 0, "max": 999, "pad": 3},
                    "fade_out": {"description": "fade out", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        MockDatetimeModule.current_time = datetime.datetime(2025, 6, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_idempotency_does_not_accumulate_heat(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)

        self.assertEqual(ledger_data['system_state']['core_heat'], 2.0)

        # Re-submit exact same DNA sequence
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)

        # Heat should remain 2.0 (idempotency deduplication adds 0 heat)
        self.assertEqual(ledger_data['system_state']['core_heat'], 2.0)

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_thermal_lockout_and_no_silent_drains(self):
        sequences = [f"VOL0000000000{i}" for i in range(1, 7)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(sequences) + "\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        err = cm.exception
        self.assertEqual(err.consequence, CONSEQUENCE_APPLIED)
        self.assertEqual(err.refusal_reason, REFUSAL_REASON)
        self.assertEqual(err.hint, NEXT_ACTION_HINT)
        self.assertIn(CONSEQUENCE_APPLIED, str(err))
        self.assertIn(REFUSAL_REASON, str(err))
        self.assertIn(NEXT_ACTION_HINT, str(err))

        # Check that 5 sequences were processed (5 * 2.0 = 10.0 heat), and state persisted at limit
        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)

        self.assertEqual(ledger_data['system_state']['core_heat'], 10.0)
        self.assertEqual(len(ledger_data['ledger']), 5)

        # Test process_once in main.py: verify input file is NOT cleared when thermal lockout occurs
        if 'main' in sys.modules:
            del sys.modules['main']
        import main

        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("VOL00000000006\n")

        with patch('main.clear_input_file') as mock_clear:
            with self.assertRaises(SystemExit):
                main.process_once()

            mock_clear.assert_not_called()

        with open(self.input_file, 'r', encoding='utf-8') as f:
            content = f.read().strip()
        self.assertEqual(content, "VOL00000000006", "Unprocessed DNA sequence must NOT be drained silently on refusal")

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_thermal_dissipation(self):
        sequences = [f"VOL0000000000{i}" for i in range(1, 6)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(sequences) + "\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)
        self.assertEqual(ledger_data['system_state']['core_heat'], 10.0)

        # Advance mock time by 4 seconds (4s * 0.5 units/s = 2.0 heat dissipated)
        MockDatetimeModule.current_time += datetime.timedelta(seconds=4)

        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("VOL00000000006\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)

        # 10.0 - 2.0 dissipated + 2.0 for new sequence = 10.0
        self.assertEqual(ledger_data['system_state']['core_heat'], 10.0)
        self.assertIn("VOL00000000006", ledger_data['ledger'])

if __name__ == '__main__':
    unittest.main()
