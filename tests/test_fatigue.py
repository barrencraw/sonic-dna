import unittest
import os
import json
import time
import shutil
import tempfile
from utils.dna_ui import main as run_batch, MAX_HEAT, HEAT_PER_ITEM, COOLING_RATE_PER_SEC, ThermalOverloadError

class TestFatigue(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.out_dir = os.path.join(self.data_dir, 'output')
        os.makedirs(self.raw_dir)
        os.makedirs(self.out_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')

        # Copy rules folder to test_dir
        self.rules_dir = os.path.join(self.test_dir, 'rules')
        shutil.copytree(os.path.join(os.getcwd(), 'rules'), self.rules_dir)

        # Patch os.getcwd for dna_ui
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation(self):
        # Create input with 3 items
        with open(self.input_file, 'w') as f:
            f.write("VOL08900750712\nVOL08900750713\nVOL08900750714\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # Expected heat: 3 items * HEAT_PER_ITEM
        self.assertAlmostEqual(state['system_heat'], 3 * HEAT_PER_ITEM)

    def test_safety_lockout(self):
        # Create input exceeding MAX_HEAT
        item_count = int(MAX_HEAT / HEAT_PER_ITEM) + 1
        with open(self.input_file, 'w') as f:
            for i in range(item_count):
                f.write(f"VOL08900750{i:03d}\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # Heat should be at or near MAX_HEAT (it stops when it hits/exceeds)
        self.assertGreaterEqual(state['system_heat'], MAX_HEAT)

        # Consistency check: items processed before lockout MUST be in output JSON
        json_output = os.path.join(self.out_dir, 'toSequence_parsed.json')
        with open(json_output, 'r') as f:
            data = json.load(f)

        # We expect exactly MAX_HEAT / HEAT_PER_ITEM items
        expected_count = int(MAX_HEAT / HEAT_PER_ITEM)
        self.assertEqual(len(data), expected_count)

    def test_cooling(self):
        # Pre-set high heat in ledger
        initial_heat = 5.0
        # Set timestamp to 100 seconds ago
        last_ts = time.time() - 100

        state = {
            "system_heat": initial_heat,
            "last_processed_timestamp": last_ts,
            "ledger": {}
        }
        with open(self.ledger_path, 'w') as f:
            json.dump(state, f)

        # Run batch with no new items
        with open(self.input_file, 'w') as f:
            pass

        run_batch()

        with open(self.ledger_path, 'r') as f:
            new_state = json.load(f)

        # Expected cooling: 100s * COOLING_RATE_PER_SEC = 1.0
        # heat: 5.0 - 1.0 = 4.0
        self.assertLess(new_state['system_heat'], initial_heat)
        self.assertAlmostEqual(new_state['system_heat'], initial_heat - (100 * COOLING_RATE_PER_SEC), places=1)

if __name__ == '__main__':
    unittest.main()
