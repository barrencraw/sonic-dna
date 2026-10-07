import sys
from unittest.mock import MagicMock

# Mock GUI dependencies before import
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

import os
import json
import shutil
import tempfile
import datetime
import unittest
from unittest.mock import patch, MagicMock

from utils.dna_ui import run_batch, ThermalOverloadError, load_ledger

class MockDatetimeModule:
    class datetime:
        current_time = datetime.datetime(2026, 3, 30, 12, 0, 0, tzinfo=datetime.timezone.utc)
        timezone = datetime.timezone

        @classmethod
        def now(cls, tz=None):
            return cls.current_time

        @classmethod
        def strptime(cls, date_string, format_string):
            return datetime.datetime.strptime(date_string, format_string)

    timezone = datetime.timezone

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

        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "master": {"description": "master volume", "min": 0, "max": 999, "pad": 3},
                    "bus_a": {"description": "bus a volume", "min": 0, "max": 999, "pad": 3},
                    "bus_b": {"description": "bus b volume", "min": 0, "max": 999, "pad": 3},
                    "headroom": {"description": "headroom", "min": 0, "max": 99, "pad": 2}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_heat_accumulation_and_lockout(self):
        """5 sequences add 10.0 heat units, triggering Thermal Lockout on the 6th sequence."""
        MockDatetimeModule.datetime.current_time = datetime.datetime(2026, 3, 30, 12, 0, 0, tzinfo=datetime.timezone.utc)

        sequences = [
            "VOL00100100101",
            "VOL00200200202",
            "VOL00300300303",
            "VOL00400400404",
            "VOL00500500505",
            "VOL00600600606"
        ]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch(correlation_id="fatigue-test-1")

        err_msg = str(cm.exception)
        self.assertIn("Thermal Lockout", err_msg)
        self.assertIn("Heat Accumulation", err_msg)
        self.assertIn("Wait for dissipation. The system is indifferent to your deadlines.", err_msg)

        ledger_data = load_ledger(self.ledger_file)
        self.assertEqual(ledger_data['system_state']['core_heat'], 10.0)

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_cooling_decay(self):
        """Core heat dissipates at 0.5 units/second."""
        MockDatetimeModule.datetime.current_time = datetime.datetime(2026, 3, 30, 12, 0, 0, tzinfo=datetime.timezone.utc)

        sequences = [
            "VOL00100100101",
            "VOL00200200202",
            "VOL00300300303",
            "VOL00400400404",
            "VOL00500500505"
        ]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        run_batch(correlation_id="fatigue-test-2a")

        ledger_data = load_ledger(self.ledger_file)
        self.assertEqual(ledger_data['system_state']['core_heat'], 10.0)

        # Advance simulated time by 10 seconds (10s * 0.5 = 5.0 heat dissipated -> 5.0 heat left)
        MockDatetimeModule.datetime.current_time = datetime.datetime(2026, 3, 30, 12, 0, 10, tzinfo=datetime.timezone.utc)

        new_sequence = "VOL00600600606"
        with open(self.input_file, 'w') as f:
            f.write(new_sequence + "\n")

        run_batch(correlation_id="fatigue-test-2b")

        ledger_data = load_ledger(self.ledger_file)
        # 10.0 - 5.0 (cooling) + 2.0 (new sequence) = 7.0 core heat
        self.assertEqual(ledger_data['system_state']['core_heat'], 7.0)

if __name__ == '__main__':
    unittest.main()
