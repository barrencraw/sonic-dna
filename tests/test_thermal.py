import sys
from unittest.mock import MagicMock, patch

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

import unittest
import os
import shutil
import tempfile
import json
import time
from utils.dna_ui import main as run_batch, DNAStatus, HEAT_PER_ITEM, HEAT_LIMIT

class TestThermalDebt(unittest.TestCase):
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
        """Verify that processing DNA increases system heat."""
        dna_list = ["V100", "V200", "V300"]
        with open(self.input_file, 'w') as f:
            for dna in dna_list:
                f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)
            # 3 items * 5.0 heat = 15.0
            self.assertEqual(data["system_heat"], 15.0)
            self.assertEqual(len(data["ledger"]), 3)
            for dna in dna_list:
                self.assertEqual(data["ledger"][dna]["terminal_outcome"], DNAStatus.SUCCESS.value)

    def test_thermal_lockout(self):
        """Verify that exceeding heat limit results in REFUSED outcomes."""
        # HEAT_LIMIT is 100.0, HEAT_PER_ITEM is 5.0.
        # 21 items should exceed the limit.
        dna_list = [f"V{i:03}" for i in range(25)]
        with open(self.input_file, 'w') as f:
            for dna in dna_list:
                f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)
            # It should stop at exactly 100.0 (20 items * 5.0)
            # The 21st item would be 105.0 -> REFUSED
            self.assertEqual(data["system_heat"], 100.0)

            refused_count = 0
            success_count = 0
            for dna in dna_list:
                outcome = data["ledger"][dna]["terminal_outcome"]
                if outcome == DNAStatus.REFUSED.value:
                    refused_count += 1
                elif outcome == DNAStatus.SUCCESS.value:
                    success_count += 1

            self.assertEqual(success_count, 20)
            self.assertEqual(refused_count, 5)

    def test_heat_dissipation(self):
        """Verify that heat dissipates over time."""
        dna = "V100"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # 1. Process one item to get 5.0 heat
        with patch('time.time', return_value=1000.0):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)
            self.assertEqual(data["system_heat"], 5.0)

        # 2. Wait 4 seconds (0.5 heat/sec * 4 = 2.0 dissipated)
        # Next run should have 5.0 - 2.0 = 3.0 heat before adding new item
        dna2 = "V200"
        with open(self.input_file, 'w') as f:
            f.write(dna2 + "\n")

        with patch('time.time', return_value=1004.0):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)
            # (5.0 - 2.0) + 5.0 = 8.0
            self.assertEqual(data["system_heat"], 8.0)

    def test_idempotency_no_extra_heat(self):
        """Verify that idempotency hits (skipped items) do not add heat."""
        dna = "V100"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch() # 5.0 heat

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)
            self.assertEqual(data["system_heat"], 5.0)

        # Run again with same DNA
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch() # Should be skipped, heat stays 5.0 (modulo minor dissipation if time passes)

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)
            # Since we didn't mock time, it might be slightly less than 5.0 due to dissipation
            self.assertLessEqual(data["system_heat"], 5.0)
            self.assertGreater(data["system_heat"], 4.0)

if __name__ == '__main__':
    unittest.main()
