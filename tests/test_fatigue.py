import unittest
import os
import json
import shutil
import tempfile
import time
from utils.dna_ui import main as run_batch, ThermalOverloadError, MAX_HEAT, HEAT_PER_ITEM

class TestFatigue(unittest.TestCase):
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
        """Verify that heat accumulates per item."""
        # Create input with 5 items
        with open(self.input_file, 'w') as f:
            for i in range(5):
                f.write(f"V{str(i).zfill(3)}\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        self.assertAlmostEqual(state['system_heat'], 5.0 * HEAT_PER_ITEM)

    def test_thermal_overload_refusal(self):
        """Verify that batch is refused when MAX_HEAT is reached."""
        # Create input with more than MAX_HEAT items
        num_items = int(MAX_HEAT / HEAT_PER_ITEM) + 1
        with open(self.input_file, 'w') as f:
            for i in range(num_items):
                f.write(f"V{str(i).zfill(3)}\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # It should have processed exactly MAX_HEAT items before raising
        self.assertAlmostEqual(state['system_heat'], MAX_HEAT)
        self.assertEqual(len(state['ledger']), int(MAX_HEAT))

    def test_cooling_over_time(self):
        """Verify that system cools down over time."""
        # 1. Fill up heat
        with open(self.input_file, 'w') as f:
            for i in range(5):
                f.write(f"V{str(i).zfill(3)}\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            state_initial = json.load(f)
        initial_heat = state_initial['system_heat']
        self.assertAlmostEqual(initial_heat, 5.0)

        # 2. Simulate time passing by manually adjusting the timestamp in ledger
        state_initial['last_processed_timestamp'] -= 100 # 100 seconds ago
        with open(self.ledger_path, 'w') as f:
            json.dump(state_initial, f)

        # 3. Run again with 1 new item
        with open(self.input_file, 'w') as f:
            f.write("V999\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state_final = json.load(f)

        # Cooling = 100 * 0.01 = 1.0
        # Heat should be 5.0 - 1.0 + 1.0 = 5.0
        self.assertAlmostEqual(state_final['system_heat'], 5.0, places=2)

if __name__ == '__main__':
    unittest.main()
