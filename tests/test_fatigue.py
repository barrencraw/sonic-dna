import os
import json
import shutil
import unittest
from utils.dna_ui import main as run_batch

class TestFatigue(unittest.TestCase):
    def setUp(self):
        # Setup paths
        self.project_root = os.getcwd()
        self.test_dir = os.path.join(self.project_root, 'test_data_fatigue')
        self.raw_folder = os.path.join(self.test_dir, 'data', 'raw')
        self.output_folder = os.path.join(self.test_dir, 'data', 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.state_path = os.path.join(self.test_dir, 'data', 'system_state.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_heat_accumulation_and_cooling(self):
        # VOL0890... -> amp = 890 -> heat gain = 8.9
        dna_vol = "VOL08900750712"

        with open(self.input_file, 'w') as f:
            f.write(dna_vol + "\n")

        # Batch 1: Start at 0.0, cool to 0.0, gain 8.9 -> 8.9
        run_batch(data_dir=self.test_dir)

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertAlmostEqual(state['system_heat'], 8.9)

        # Batch 2: Start at 8.9, cool by 1.0 -> 7.9, gain 8.9 -> 16.8
        with open(self.input_file, 'w') as f:
            f.write("VOL08900750711\n") # Different DNA to avoid idempotency hit

        run_batch(data_dir=self.test_dir)

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertAlmostEqual(state['system_heat'], 16.8)

    def test_clarity_penalty_and_refusal(self):
        # 1. Increase heat above 0
        dna_vol = "VOL05000750712" # Heat +5.0
        with open(self.input_file, 'w') as f:
            f.write(dna_vol + "\n")
        run_batch(data_dir=self.test_dir)

        # 2. Process Clarity DNA and check penalty
        # CLAZN0900015 -> noise_floor.value = 90
        # Expected: heat = 5.0 - 1.0 (cooling) = 4.0. Penalty = int(4.0) = 4.
        # New noise_floor = 90 - 4 = 86.
        dna_cla = "CLAZN0900015"
        with open(self.input_file, 'w') as f:
            f.write(dna_cla + "\n")
        run_batch(data_dir=self.test_dir)

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        cla_entry = next(e for e in data if e['dna'] == dna_cla)
        self.assertEqual(cla_entry['parsed']['noise_floor']['value'], 86)

        # 3. Increase heat above 10.0
        dna_vol_high = "VOL09000750712" # Current heat ~4.0. Batch start: 3.0. Gain +9.0 -> 12.0
        with open(self.input_file, 'w') as f:
            f.write("VOL09000750713\n")
        run_batch(data_dir=self.test_dir)

        # 4. Process Clarity and expect refusal (ThermalOverloadError)
        with open(self.input_file, 'w') as f:
            f.write("CLAZN0900016\n")
        run_batch(data_dir=self.test_dir)

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        refused_entry = next(e for e in data if e['dna'] == "CLAZN0900016")
        self.assertIn("thermal overload", refused_entry['error'])

if __name__ == '__main__':
    unittest.main()
