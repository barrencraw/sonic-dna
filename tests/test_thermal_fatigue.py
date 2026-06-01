import unittest
import os
import json
import shutil
import time
from utils.dna_ui import main as run_batch, ThermalOverloadError

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_dir = os.path.join(self.project_root, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.state_path = os.path.join(self.data_dir, 'system_state.json')
        self.ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')

        # Clean up and setup directories
        if os.path.exists(self.data_dir):
            shutil.rmtree(self.data_dir)
        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)

    def tearDown(self):
        if os.path.exists(self.data_dir):
            shutil.rmtree(self.data_dir)

    def write_dna(self, dna_list):
        with open(os.path.join(self.raw_dir, 'toSequence.txt'), 'w') as f:
            for dna in dna_list:
                f.write(f"{dna}\n")

    def test_heat_accumulation(self):
        # 0.1 per item + 0.2 for Volume.
        # VOL08900750712 -> Volume rule. Heat gain = 0.3
        # BUT: idempotency check is BEFORE heat accumulation.
        # If we send 5 identical lines, only the first one processes.
        # So heat should be 0.3.
        self.write_dna(['VOL08900750712', 'VOL00000000000', 'VOL11111111111'])
        run_batch()

        with open(self.state_path, 'r') as f:
            state = json.load(f)

        # 3 * 0.3 = 0.9
        self.assertAlmostEqual(state['system_heat'], 0.9, places=2)

    def test_thermal_noise(self):
        # Trigger noise (threshold 7.0)
        # We need ~24 Volume strings to exceed 7.0 (24 * 0.3 = 7.2)
        # Or just manually set the state
        os.makedirs(self.data_dir, exist_ok=True)
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 8.0, "last_update": time.time()}, f)

        self.write_dna(['VOL08900750712'])
        run_batch()

        output_json = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(output_json, 'r') as f:
            parsed = json.load(f)

        # Original amp was 890. With noise (0.9 multiplier), it should be 801.0
        self.assertEqual(parsed[0]['parsed']['amp'], 801.0)

    def test_thermal_overload_refusal(self):
        # Trigger overload (threshold 10.0)
        os.makedirs(self.data_dir, exist_ok=True)
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 9.9, "last_update": time.time()}, f)

        # 9.9 + 0.3 = 10.2 > 10.0. Refusal!

        self.write_dna(['VOL08900750712'])

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # Ledger might not exist if no items were ever successfully processed
        if os.path.exists(self.ledger_path):
            with open(self.ledger_path, 'r') as f:
                ledger = json.load(f)
            self.assertEqual(len(ledger), 0)

    def test_cooling(self):
        os.makedirs(self.data_dir, exist_ok=True)
        # Set heat to 5.0, last update 100 seconds ago
        # Cooling rate 0.0083. 100 * 0.0083 = 0.83
        # Expected heat: 5.0 - 0.83 = 4.17
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 5.0, "last_update": time.time() - 100}, f)

        self.write_dna(['VOL08900750712'])
        run_batch()

        with open(self.state_path, 'r') as f:
            state = json.load(f)

        # 4.17 + 0.3 = 4.47
        self.assertAlmostEqual(state['system_heat'], 4.47, places=2)

if __name__ == '__main__':
    unittest.main()
