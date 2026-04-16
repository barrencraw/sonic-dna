import os
import json
import shutil
import unittest
import tempfile
from utils.dna_ui import main as run_batch

class TestFatigue(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.raw_folder = os.path.join(self.test_dir, 'raw')
        self.output_folder = os.path.join(self.test_dir, 'output')
        os.makedirs(self.raw_folder)
        os.makedirs(self.output_folder)

        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.state_path = os.path.join(self.test_dir, 'system_state.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation_and_penalty(self):
        # 1. Process High-Amp VOL (100.0%) -> Adds 10.0 heat
        # VOL0890... amp=0890=89.0 -> 8.9 heat
        dna_vol = "VOL10000750712"
        with open(self.input_file, 'w') as f:
            f.write(dna_vol + "\n")

        run_batch(data_dir=self.test_dir)

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 10.0)

        # 2. Process CLA DNA -> Should have penalty of 10dB
        # CLAZN0900015 -> noise_floor=90 -> should become 80
        dna_cla = "CLAZN0900015"
        with open(self.input_file, 'w') as f:
            f.write(dna_cla + "\n")

        # Natural cooling will trigger at start of batch: 10.0 -> 9.0
        run_batch(data_dir=self.test_dir)

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 9.0)

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        # Find the CLA entry
        cla_entry = next(e for e in data if e['dna'] == dna_cla)
        # 9.0 heat -> int(9.0) = 9 penalty. 90 - 9 = 81.
        self.assertEqual(cla_entry['parsed']['noise_floor']['value'], 81)

    def test_thermal_overload_refusal(self):
        # 1. Max heat: VOL1000 (10.0 heat) + VOL0500 (5.0 heat) = 15.0 heat
        with open(self.input_file, 'w') as f:
            f.write("VOL10000750712\nVOL05000750712\n")

        run_batch(data_dir=self.test_dir)

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 15.0)

        # 2. Try CLA -> Should be refused
        dna_cla = "CLAZN0900015"
        with open(self.input_file, 'w') as f:
            f.write(dna_cla + "\n")

        # Natural cooling: 15.0 -> 14.0. Still > 10.0.
        run_batch(data_dir=self.test_dir)

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        cla_entry = next(e for e in data if e['dna'] == dna_cla)
        self.assertIn("error", cla_entry)
        self.assertIn("safety threshold", cla_entry['error'])

    def test_idempotency_no_extra_heat(self):
        dna_vol = "VOL05000750712" # 5.0 heat
        with open(self.input_file, 'w') as f:
            f.write(dna_vol + "\n")

        run_batch(data_dir=self.test_dir)

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        initial_heat = state['system_heat']
        self.assertEqual(initial_heat, 5.0)

        # Run again with same DNA
        with open(self.input_file, 'w') as f:
            f.write(dna_vol + "\n")

        # Cooling applies at start: 5.0 -> 4.0
        run_batch(data_dir=self.test_dir)

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        # Should be 4.0 (initial 5.0 - 1.0 cooling + 0.0 gain because of idempotency)
        self.assertEqual(state['system_heat'], 4.0)

if __name__ == '__main__':
    unittest.main()
