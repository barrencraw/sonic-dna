import os
import json
import shutil
import unittest
import time
import tempfile
from utils.dna_ui import main as run_batch, ThermalOverloadError

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

        # Create a dummy rule
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {"v": {"description": "v", "min": 0, "max": 9, "pad": 1}}
            }, f)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_dir, 'ledger.json')

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_thermal_buildup_and_refusal(self):
        # MAX_HEAT is 10.0, HEAT_PER_ITEM is 1.0.
        # 11 items should trigger refusal.
        dnas = [f"VOL{i}" for i in range(11)]
        with open(self.input_file, 'w') as f:
            for dna in dnas:
                f.write(dna + "\n")

        # We need to mock apply_cooling to return fixed heat to avoid jitter
        # Actually, let's just use assertAlmostEqual more broadly
        run_batch(base_dir=self.test_dir)

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # Should have processed 10 items (heat 10.0), then refused the 11th.
        self.assertAlmostEqual(state["system_heat"], 10.0, places=2)
        self.assertEqual(len(state["ledger"]), 10)

        # Next run with more DNA should refuse immediately if no cooling
        with open(self.input_file, 'w') as f:
            f.write("VOL9\n")

        run_batch(base_dir=self.test_dir)

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
        self.assertAlmostEqual(state["system_heat"], 10.0, places=2)
        self.assertEqual(len(state["ledger"]), 10) # Still 10

    def test_cooling_over_time(self):
        # Set high heat in ledger
        state = {
            "system_heat": 10.0,
            "last_processed_timestamp": time.time() - 100, # 100 seconds ago
            "ledger": {}
        }
        with open(self.ledger_path, 'w') as f:
            json.dump(state, f)

        # COOLING_RATE_PER_SEC is 0.01. 100 seconds = 1.0 heat reduction.
        # We need an input file for run_batch to actually do something and save
        with open(self.input_file, 'w') as f:
            f.write("VOL1\n")

        run_batch(base_dir=self.test_dir)

        with open(self.ledger_path, 'r') as f:
            new_state = json.load(f)

        # Expected: 10.0 - (100 * 0.01) + 1.0 (for processing VOL1) = 10.0
        self.assertAlmostEqual(new_state["system_heat"], 10.0, places=1)

if __name__ == '__main__':
    unittest.main()
