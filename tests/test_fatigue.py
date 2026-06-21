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
import time
from unittest.mock import patch
from utils.dna_ui import main as run_batch, MAX_HEAT, HEAT_PER_ITEM, COOLING_RATE_PER_SEC

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

    def write_input(self, dna_list):
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(input_file, 'w') as f:
            for dna in dna_list:
                f.write(f"{dna}\n")

    def get_ledger(self):
        ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')
        if os.path.exists(ledger_path):
            with open(ledger_path, 'r') as f:
                return json.load(f)
        return {}

    def test_heat_accumulation(self):
        """Verify that processing DNA increases system heat."""
        self.write_input(["V001", "V002"])
        run_batch()

        state = self.get_ledger()
        self.assertIn('system_heat', state)
        self.assertEqual(state['system_heat'], 2 * HEAT_PER_ITEM)

    def test_cooling(self):
        """Verify that heat dissipates over time."""
        # Set initial high heat
        ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')
        initial_time = time.time() - 100 # 100 seconds ago
        initial_state = {
            'system_heat': 5.0,
            'last_processed_timestamp': initial_time,
            'ledger': {}
        }
        os.makedirs(os.path.dirname(ledger_path), exist_ok=True)
        with open(ledger_path, 'w') as f:
            json.dump(initial_state, f)

        self.write_input(["V001"])
        run_batch()

        state = self.get_ledger()
        expected_heat = 5.0 - (100 * COOLING_RATE_PER_SEC) + HEAT_PER_ITEM
        self.assertAlmostEqual(state['system_heat'], expected_heat, places=2)

    def test_thermal_overload_refusal(self):
        """Verify that processing is refused when MAX_HEAT is reached."""
        # Create a lot of DNA strings
        count = int(MAX_HEAT / HEAT_PER_ITEM) + 5
        dna_list = [f"V{i:03d}" for i in range(count)]
        self.write_input(dna_list)

        run_batch()

        state = self.get_ledger()
        # Should have processed exactly as many as fit within MAX_HEAT
        max_items = int(MAX_HEAT / HEAT_PER_ITEM)
        self.assertEqual(len(state['ledger']), max_items)
        self.assertTrue(state['system_heat'] <= MAX_HEAT)
        self.assertAlmostEqual(state['system_heat'], max_items * HEAT_PER_ITEM)

    def test_idempotency_does_not_increase_heat(self):
        """Verify that deduplication hits do not increase system heat."""
        self.write_input(["V001"])
        run_batch()
        state1 = self.get_ledger()
        heat1 = state1['system_heat']

        # Run again with same input
        run_batch()
        state2 = self.get_ledger()
        heat2 = state2['system_heat']

        # Heat should only have increased by cooling since last run (which is negligible here)
        # but certainly NOT by another HEAT_PER_ITEM
        self.assertTrue(heat2 <= heat1)

if __name__ == '__main__':
    unittest.main()
