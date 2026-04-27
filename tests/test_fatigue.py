import unittest
import os
import shutil
import tempfile
import json
from utils.dna_ui import main as run_batch, load_system_state

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
        self.state_file = os.path.join(self.data_dir, 'system_state.json')
        self.json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')

        # Mock Volume and Clarity rules
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume", "prefix": "VOL",
                "subvars": {
                    "amp": {"description": "amp", "min": 0, "max": 1000, "pad": 4},
                    "lr": {"description": "lr", "min": 0, "max": 100, "pad": 3},
                    "sur": {"description": "sur", "min": 0, "max": 10, "pad": 2},
                    "head": {"description": "head", "min": 0, "max": 60, "pad": 2}
                }
            }, f)
        with open(os.path.join(self.rules_dir, 'rules_Clarity.json'), 'w') as f:
            json.dump({
                "variable": "Clarity", "prefix": "CLA",
                "subvars": {
                    "spectral_flat": {"class": "Z-A", "description": "flat"},
                    "noise_floor": {"min": 0, "max": 120, "pad": 3, "sign": "N", "description": "noise"},
                    "thd": {"min": 0, "max": 1000, "pad": 4, "description": "thd"}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation_and_cooling(self):
        # Initial heat = 0.0. Batch cooling = -1.0 -> 0.0.
        # VOL0500... -> amp=500 -> heat_gain = 5.0.
        # Result: 0.0 + 5.0 = 5.0.
        with open(self.input_file, 'w') as f:
            f.write("VOL05000750712\n")

        run_batch()
        self.assertEqual(load_system_state(self.state_file), 5.0)

        # Natural cooling in next batch.
        # Initial heat = 5.0. Batch cooling = -1.0 -> 4.0.
        with open(self.input_file, 'w') as f:
            f.write("VOL00000750712\n") # New DNA, amp=0

        run_batch()
        self.assertEqual(load_system_state(self.state_file), 4.0)

    def test_clarity_penalty(self):
        # Set heat to 6.0
        # Batch cooling makes it 5.0.
        # Penalty: noise -= int(5.0) = 5. thd += int(5.0 * 10) = 50.
        with open(self.state_file, 'w') as f:
            json.dump({'system_heat': 6.0}, f)

        dna = "CLAZN0900015"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.json_out, 'r') as f:
            data = json.load(f)

        parsed = data[0]['parsed']
        self.assertEqual(parsed['noise_floor']['value'], 85) # 90 - 5
        self.assertEqual(parsed['thd'], 65) # 15 + 50

    def test_thermal_overload_refusal(self):
        # Set heat to 12.0
        # Batch cooling makes it 11.0.
        # 11.0 > 10.0 -> refusal.
        with open(self.state_file, 'w') as f:
            json.dump({'system_heat': 12.0}, f)

        dna = "CLAZN0900015"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.json_out, 'r') as f:
            data = json.load(f)

        self.assertIn('error', data[0])
        self.assertIn("Heat 11.00 exceeds threshold 10.0", data[0]['error'])

if __name__ == '__main__':
    unittest.main()
