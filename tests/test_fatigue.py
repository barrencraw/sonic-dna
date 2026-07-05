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
sys.modules["numpy"] = MagicMock()
sys.modules["scipy"] = MagicMock()
sys.modules["scipy.io"] = MagicMock()
sys.modules["scipy.io.wavfile"] = MagicMock()

import unittest
import os
import shutil
import tempfile
import json
import time
from utils.dna_ui import main as run_batch, ThermalOverloadError

class TestFatigue(unittest.TestCase):
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

        # Mock a rule file
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

    def test_heat_accumulation(self):
        """Verify that processing DNA strings increases system heat."""
        with open(self.input_file, 'w') as f:
            f.write("V100\nV200\n")

        run_batch()

        ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')
        with open(ledger_path, 'r') as f:
            data = json.load(f)
            # 2 strings * 5.0 heat = 10.0
            self.assertEqual(data["system_heat"], 10.0)

    def test_thermal_lockout(self):
        """Verify that reaching 100.0 heat causes ThermalOverloadError."""
        # Pre-seed ledger with high heat
        ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')
        os.makedirs(os.path.dirname(ledger_path), exist_ok=True)
        with open(ledger_path, 'w') as f:
            json.dump({
                "system_heat": 110.0,
                "last_processed_timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
                "ledger": {}
            }, f)

        with open(self.input_file, 'w') as f:
            f.write("V300\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

    def test_partial_batch_success_before_lockout(self):
        """Verify that items processed before lockout are saved."""
        # Seed heat so that one item passes and the next triggers lockout
        ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')
        os.makedirs(os.path.dirname(ledger_path), exist_ok=True)
        with open(ledger_path, 'w') as f:
            json.dump({
                "system_heat": 98.0,
                "last_processed_timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
                "ledger": {}
            }, f)

        with open(self.input_file, 'w') as f:
            f.write("V100\nV200\n")

        # V100: heat becomes 98+5 = 103
        # V200: lockout should occur

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # Verify V100 was saved to ledger and output
        with open(ledger_path, 'r') as f:
            data = json.load(f)
            self.assertIn("V100", data["ledger"])
            self.assertNotIn("V200", data["ledger"])
            # 98 - (epsilon) + 5 = ~103
            self.assertGreater(data["system_heat"], 102.0)
            self.assertLess(data["system_heat"], 103.1)

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["dna"], "V100")

    def test_heat_dissipation(self):
        """Verify that heat dissipates over time."""
        # Pre-seed ledger with heat and an old timestamp
        old_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time() - 20)) # 20 seconds ago
        ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')
        os.makedirs(os.path.dirname(ledger_path), exist_ok=True)
        with open(ledger_path, 'w') as f:
            json.dump({
                "system_heat": 50.0,
                "last_processed_timestamp": old_time,
                "ledger": {}
            }, f)

        with open(self.input_file, 'w') as f:
            f.write("V400\n")

        run_batch()

        with open(ledger_path, 'r') as f:
            data = json.load(f)
            # Dissipation: 20s * 0.5 = 10.0 units
            # Initial 50.0 - 10.0 = 40.0
            # Plus 5.0 for V400 = 45.0
            self.assertLess(data["system_heat"], 45.1)
            self.assertGreater(data["system_heat"], 44.0)

if __name__ == '__main__':
    unittest.main()
