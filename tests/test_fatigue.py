import os
import json
import shutil
import unittest
import tempfile
from utils.dna_ui import main as run_batch, ThermalOverloadError

class TestFatigue(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.state_path = os.path.join(self.data_dir, 'system_state.json')
        self.json_output = os.path.join(self.output_dir, 'toSequence_parsed.json')

        # We need the real rules for parsing
        self.project_root = os.getcwd()
        self.rules_dir = os.path.join(self.project_root, 'rules')
        # Link rules to test dir if needed, but DNACalculator uses os.getcwd() by default if not specified
        # Actually dna_ui.py uses os.path.join(project_root, 'rules') where project_root = os.getcwd()
        # So I should stay in project root but point data_dir

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_heat_gain_and_penalty(self):
        # 1. Start with 0 heat
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 0.0}, f)

        # Process a high volume DNA (VOL + amp=1000) -> heat should gain 10.0
        # Passive dissipation at start: 0.0 - 0.5 -> 0.0
        # Then VOL1000... -> +10.0 heat
        # VOL08900750712 -> amp=890 -> +8.9 heat
        dna_vol = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna_vol + "\n")

        run_batch(data_dir=self.data_dir)

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 8.9)

        # 2. Process Clarity DNA and check penalty
        # Heat is 8.9. int(8.9) = 8.
        # CLA: noise_floor N090 -> N(90-8) = N082
        # CLA: thd 0015 -> 15 + 8*10 = 95
        dna_cla = "CLAZN0900015"
        with open(self.input_file, 'w') as f:
            f.write(dna_cla + "\n")

        # Passive dissipation at start: 8.9 - 0.5 = 8.4
        # Penalty: int(8.4) = 8
        run_batch(data_dir=self.data_dir)

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        cla_entry = next(e for e in data if e['dna'] == dna_cla)
        self.assertEqual(cla_entry['parsed']['noise_floor']['value'], 82)
        self.assertEqual(cla_entry['parsed']['thd'], 95)

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 8.4)

    def test_thermal_overload_refusal(self):
        # Set heat to 11.0
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 11.0}, f)

        # Passive dissipation: 11.0 - 0.5 = 10.5
        # 10.5 > 10.0 -> Refusal

        dna = "VOL01000750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch(data_dir=self.data_dir)

        # Check that heat was dissipated even on refusal
        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 10.5)

    def test_passive_dissipation_no_dna(self):
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 1.0}, f)

        # Empty input
        with open(self.input_file, 'w') as f:
            f.write("")

        run_batch(data_dir=self.data_dir)

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 0.5)

if __name__ == '__main__':
    unittest.main()
