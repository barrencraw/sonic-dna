import unittest
import os
import shutil
import tempfile
import json
from utils.dna_ui import main as run_batch

class TestFatigueSystem(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.raw_dir = os.path.join(self.test_dir, 'data', 'raw')
        self.output_dir = os.path.join(self.test_dir, 'data', 'output')
        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.state_file = os.path.join(self.test_dir, 'data', 'system_state.json')

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_heat_gain_from_volume(self):
        # VOL0890... -> amp=890 -> heat_gain=8.9
        with open(self.input_file, 'w') as f:
            f.write("VOL08900750712\n")

        run_batch(data_dir=self.test_dir)

        with open(self.state_file, 'r') as f:
            state = json.load(f)

        self.assertAlmostEqual(state['system_heat'], 8.9)

    def test_clarity_penalty(self):
        # Set heat to 5.0
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        with open(self.state_file, 'w') as f:
            json.dump({"system_heat": 5.0}, f)

        # CLAZN0900015 -> noise_floor=90. Penalty = int(5.0) = 5. New floor = 85.
        with open(self.input_file, 'w') as f:
            f.write("CLAZN0900015\n")

        run_batch(data_dir=self.test_dir)

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)

        self.assertEqual(data[0]['parsed']['noise_floor']['value'], 85)

    def test_thermal_overload_refusal(self):
        # Set heat to 11.0 (threshold 10.0)
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        with open(self.state_file, 'w') as f:
            json.dump({"system_heat": 11.0}, f)

        with open(self.input_file, 'w') as f:
            f.write("CLAZN0900015\n")

        run_batch(data_dir=self.test_dir)

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)

        self.assertIn("Thermal overload", data[0]['error'])

if __name__ == '__main__':
    unittest.main()
