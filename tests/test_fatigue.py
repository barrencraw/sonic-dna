import unittest
import os
import json
import shutil
import tempfile
from utils.dna_ui import main as run_batch

class TestFatigueSystem(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        os.makedirs(self.raw_dir)
        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.state_file = os.path.join(self.data_dir, 'system_state.json')
        self.json_output = os.path.join(self.output_dir, 'toSequence_parsed.json')

        # Copy rules to test_dir
        self.rules_dir = os.path.join(self.test_dir, 'rules')
        shutil.copytree('rules', self.rules_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation(self):
        # VOL0500... -> amp=500 -> heat gain = 5.0
        # Natural cooling at start of batch is -1.0
        # Initial heat 0 -> 0 - 1 = 0 -> 0 + 5.0 = 5.0
        dna = "VOL05000500010"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # We need to be in the test_dir for relative rule loading if run_batch doesn't take project_root
        # But our run_batch takes data_dir and derives project_root from it
        old_cwd = os.getcwd()
        os.chdir(self.test_dir)
        try:
            run_batch(data_dir=self.data_dir)
        finally:
            os.chdir(old_cwd)

        with open(self.state_file, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 5.0)

    def test_clarity_penalty(self):
        # 1. Set heat to 5.0
        with open(self.state_file, 'w') as f:
            json.dump({'system_heat': 6.0}, f) # 6.0 - 1.0 (cooling) = 5.0

        # CLA Z N 090 0015
        dna = "CLAZN0900015"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        old_cwd = os.getcwd()
        os.chdir(self.test_dir)
        try:
            run_batch(data_dir=self.data_dir)
        finally:
            os.chdir(old_cwd)

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        # Noise floor was 90, penalty is 5 -> 90 - 5 = 85
        parsed = data[0]['parsed']
        self.assertEqual(parsed['noise_floor']['value'], 85)
        self.assertIn("Thermal noise floor penalty", parsed['noise_floor']['CONSEQUENCE_APPLIED'])

    def test_thermal_refusal(self):
        # Set heat to 11.0 (after cooling it will be 10.0)
        with open(self.state_file, 'w') as f:
            json.dump({'system_heat': 11.0}, f)

        dna = "CLAZN0900015"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        old_cwd = os.getcwd()
        os.chdir(self.test_dir)
        try:
            run_batch(data_dir=self.data_dir)
        finally:
            os.chdir(old_cwd)

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        self.assertIn("error", data[0])
        self.assertIn("System thermal overload", data[0]['error'])
        self.assertIn("REFUSAL_REASON", data[0])

    def test_natural_cooling(self):
        # Set heat to 5.0
        with open(self.state_file, 'w') as f:
            json.dump({'system_heat': 5.0}, f)

        # Process some unrelated DNA to trigger a batch
        dna = "VOL00000500010" # amp=0, heat gain=0
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        old_cwd = os.getcwd()
        os.chdir(self.test_dir)
        try:
            run_batch(data_dir=self.data_dir)
        finally:
            os.chdir(old_cwd)

        with open(self.state_file, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 4.0)

if __name__ == '__main__':
    unittest.main()
