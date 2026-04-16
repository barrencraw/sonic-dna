import os
import json
import shutil
import unittest
import tempfile
from utils.dna_ui import main as run_batch

class TestFatigue(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)

        # Link rules to test dir
        self.rules_dir = os.path.join(self.test_dir, 'rules')
        shutil.copytree(os.path.join(os.getcwd(), 'rules'), self.rules_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.state_file = os.path.join(self.data_dir, 'system_state.json')
        self.json_output = os.path.join(self.output_dir, 'toSequence_parsed.json')

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation(self):
        # VOL amp=0500 (50.0%) -> heat gain = 5.0
        dna = "VOL05000500512"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch(data_dir=self.test_dir)

        with open(self.state_file, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 5.0)

    def test_clarity_penalty(self):
        # 1. Increase heat to 5.0
        dna_vol = "VOL05000500512"
        # 2. Process Clarity
        # CLAZN0900015 -> noise_floor = 90
        dna_cla = "CLAZN0900015"

        with open(self.input_file, 'w') as f:
            f.write(f"{dna_vol}\n{dna_cla}\n")

        run_batch(data_dir=self.test_dir)

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        # Find CLA entry
        cla_entry = next(e for e in data if e['dna'] == dna_cla)
        # Noise floor should be 90 - 5 = 85
        self.assertEqual(cla_entry['parsed']['noise_floor']['value'], 85)

    def test_thermal_overload_refusal(self):
        # 1. Increase heat to 11.0
        dna_vol1 = "VOL05000500512" # +5.0
        dna_vol2 = "VOL06000500512" # +6.0
        # 2. Process Clarity (should be refused)
        dna_cla = "CLAZN0900015"

        with open(self.input_file, 'w') as f:
            f.write(f"{dna_vol1}\n{dna_vol2}\n{dna_cla}\n")

        run_batch(data_dir=self.test_dir)

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        cla_entry = next(e for e in data if e['dna'] == dna_cla)
        self.assertIn('error', cla_entry)
        self.assertIn("Thermal overload", cla_entry['error'])

if __name__ == '__main__':
    unittest.main()
