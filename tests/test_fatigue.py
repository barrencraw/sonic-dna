import os
import json
import shutil
import unittest
import tempfile
from utils.dna_ui import main as run_batch

class TestFatigue(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.project_root = self.test_dir

        # Create folder structure
        self.raw_folder = os.path.join(self.test_dir, 'data', 'raw')
        self.output_folder = os.path.join(self.test_dir, 'data', 'output')
        os.makedirs(self.raw_folder)
        os.makedirs(self.output_folder)

        # Paths
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.test_dir, 'data', 'processed_ledger.json')
        self.state_path = os.path.join(self.test_dir, 'data', 'system_state.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        # Copy rules
        self.rules_folder = os.path.join(self.test_dir, 'rules')
        shutil.copytree(os.path.join(os.getcwd(), 'rules'), self.rules_folder)

        # Change working directory to test_dir
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation_and_interference(self):
        # 1. Gain heat from Volume DNA
        # VOL + amp(4) + LR(3) + sur(2) + head(2)
        # VOL0500... -> amp = 500 -> heat_gain = 5.0
        dna_vol = "VOL05000500512"
        with open(self.input_file, 'w') as f:
            f.write(dna_vol + "\n")

        run_batch()

        # Check heat in state file (remember natural cooling -1.0 happened first)
        # Initial heat 0 -> cooling 0 -> gain 5.0 -> final 5.0
        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 5.0)

        # 2. Process Clarity DNA and check interference
        # CLAZN0900015 -> noise_floor.value = 90
        dna_cla = "CLAZN0900015"
        with open(self.input_file, 'w') as f:
            f.write(dna_cla + "\n")

        run_batch()

        # Heat before this batch: 5.0
        # Natural cooling: 5.0 - 1.0 = 4.0
        # Interference: penalty = int(4.0) = 4
        # New noise floor value: 90 - 4 = 86

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        cla_entry = next(e for e in data if e.get('rule') == 'Clarity')
        self.assertEqual(cla_entry['parsed']['noise_floor']['value'], 86)

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 4.0)

    def test_thermal_refusal(self):
        # Overheat the system
        # Initial 0 -> cooling 0 -> gain 11.0 -> 11.0
        dna_vol = "VOL11000500512"
        with open(self.input_file, 'w') as f:
            f.write(dna_vol + "\n")
        run_batch()

        # Process CLA DNA
        dna_cla = "CLAZN0900015"
        with open(self.input_file, 'w') as f:
            f.write(dna_cla + "\n")
        run_batch()

        # Heat: 11.0 - 1.0 = 10.0 (exactly 10.0 is NOT > 10.0)
        with open(self.json_output, 'r') as f:
            data = json.load(f)
        cla_entry = next(e for e in data if e.get('dna') == dna_cla)
        self.assertIn('parsed', cla_entry) # Should still work

        # Gain more heat
        dna_vol2 = "VOL02000500512" # +2.0 heat
        with open(self.input_file, 'w') as f:
            f.write(dna_vol2 + "\n")
        run_batch()
        # Heat: 10.0 - 1.0 (cooling) + 2.0 = 11.0

        # Try CLA again with DIFFERENT DNA to avoid idempotency for now
        dna_cla2 = "CLAYN0800020"
        with open(self.input_file, 'w') as f:
            f.write(dna_cla2 + "\n")
        run_batch()

        # Heat: 11.0 - 1.0 (cooling) = 10.0. STILL exactly 10.0.
        # Let's make it more extreme.

        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 15.0}, f)

        dna_cla3 = "CLAXN0700025"
        with open(self.input_file, 'w') as f:
            f.write(dna_cla3 + "\n")
        run_batch()
        # Heat: 15.0 - 1.0 = 14.0. Should REFUSE.

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        cla_refusal = next(e for e in data if e.get('dna') == dna_cla3)
        self.assertIn('error', cla_refusal)
        self.assertIn('System heat 14.00 exceeds threshold 10.0', cla_refusal['error'])

    def test_natural_cooling(self):
        # Set high heat
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 5.0}, f)

        # Process some irrelevant DNA
        with open(self.input_file, 'w') as f:
            f.write("VOL00000500512\n") # amp 0 -> heat gain 0

        run_batch()

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 4.0)

    def test_idempotency_heat_gain(self):
        dna_vol = "VOL05000500512"
        with open(self.input_file, 'w') as f:
            f.write(dna_vol + "\n")
        run_batch() # 0 - 0 + 5.0 = 5.0

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 5.0)

        # Process again
        with open(self.input_file, 'w') as f:
            f.write(dna_vol + "\n")
        run_batch() # 5.0 - 1.0 (cooling) + 0 (idempotency) = 4.0

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 4.0)

if __name__ == '__main__':
    unittest.main()
