import os
import json
import shutil
import unittest
import tempfile
from utils.dna_ui import main as run_batch

class TestFatigue(unittest.TestCase):
    def setUp(self):
        # Setup temporary project root
        self.test_dir = tempfile.mkdtemp()
        self.project_root = self.test_dir

        # Mocking os.getcwd to return our test_dir
        self.old_getcwd = os.getcwd
        os.getcwd = lambda: self.test_dir

        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.rules_folder = os.path.join(self.project_root, 'rules')

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Copy rules to test dir
        shutil.copytree(os.path.join(self.old_getcwd(), 'rules'), self.rules_folder)

        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.state_path = os.path.join(self.data_folder, 'system_state.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

    def tearDown(self):
        os.getcwd = self.old_getcwd
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation_from_volume(self):
        # VOL0890... -> amp = 890. Heat gain = 8.9
        # But wait, natural cooling -1.0 happens first if dna_list is non-empty.
        # Initial heat 0.0 -> cooling -> 0.0.
        # Then VOL adds 8.9 -> 8.9.
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertAlmostEqual(state['system_heat'], 8.9)

    def test_clarity_penalty(self):
        # 1. Add heat
        dna_vol = "VOL05000750712" # amp 500 -> heat 5.0
        with open(self.input_file, 'w') as f:
            f.write(dna_vol + "\n")
        run_batch() # Heat becomes 5.0 (cooling 0, then +5)

        # 2. Parse Clarity
        # CLAZN0900015 -> noise_floor.value = 90
        dna_cla = "CLAZN0900015"
        with open(self.input_file, 'w') as f:
            f.write(dna_cla + "\n")

        # Next run: heat 5.0 -> cooling -> 4.0.
        # Penalty = int(4.0) = 4.
        # New noise floor = 90 - 4 = 86.
        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        cla_entry = next(e for e in data if e['dna'] == dna_cla)
        self.assertEqual(cla_entry['parsed']['noise_floor']['value'], 86)
        self.assertIn("Thermal noise penalty", cla_entry['parsed']['CONSEQUENCE_APPLIED'])

    def test_thermal_overload_refusal(self):
        # 1. Add massive heat
        # VOL1000... -> amp 1000 -> heat 10.0
        dna_vol = "VOL10000750712"
        with open(self.input_file, 'w') as f:
            f.write(dna_vol + "\n")
        run_batch() # Heat = 10.0

        # Run another VOL to push it over
        with open(self.input_file, 'w') as f:
            f.write("VOL05000750712\n")
        run_batch() # Heat: 10.0 -> cooling 9.0 -> +5.0 = 14.0

        # 2. Try Clarity
        dna_cla = "CLAZN0900015"
        with open(self.input_file, 'w') as f:
            f.write(dna_cla + "\n")

        # Heat: 14.0 -> cooling 13.0.
        # 13.0 > 10.0 -> ThermalOverloadError
        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        cla_entry = next(e for e in data if e['dna'] == dna_cla)
        self.assertIn("REFUSAL_REASON: Thermal overload", cla_entry['error'])

    def test_natural_cooling(self):
        # 1. Set heat
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 5.0}, f)

        # 2. Run empty batch? (dna_ui returns early if no dna)
        # We need a dummy DNA that doesn't add heat.
        # Or just any DNA.
        with open(self.input_file, 'w') as f:
            f.write("VOL00000000000\n") # amp 0

        run_batch() # 5.0 -> 4.0 -> +0 = 4.0
        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 4.0)

    def test_idempotency_no_double_heat(self):
        dna = "VOL05000750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch() # Heat = 5.0

        # Re-run same DNA
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch() # Heat: 5.0 -> cooling 4.0 -> dedupe hit -> no heat gain

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 4.0)

if __name__ == '__main__':
    unittest.main()
