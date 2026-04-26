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
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        # Mock Volume rule
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "amp": {"min": 0, "max": 1000, "pad": 4, "description": "amp"},
                    "lr": {"min": 0, "max": 100, "pad": 3, "description": "lr"},
                    "sur": {"min": 0, "max": 10, "pad": 2, "description": "sur"},
                    "head": {"min": 0, "max": 60, "pad": 2, "description": "head"}
                }
            }, f)

        # Mock Clarity rule
        with open(os.path.join(self.rules_dir, 'rules_Clarity.json'), 'w') as f:
            json.dump({
                "variable": "Clarity",
                "prefix": "CLA",
                "subvars": {
                    "spectral_flat": {"class": "Z-A", "description": "flat"},
                    "noise_floor": {"min": 0, "max": 120, "pad": 3, "sign": "N", "description": "noise"},
                    "thd": {"min": 0, "max": 1000, "pad": 4, "description": "thd"}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.state_file = os.path.join(self.data_dir, 'system_state.json')

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation_and_cooling(self):
        # 1. Initial run: cooling (-1.0) on 0.0 stays 0.0. VOL500 adds 5.0 heat.
        with open(self.input_file, 'w') as f:
            f.write("VOL05000750712\n")

        run_batch()

        with open(self.state_file, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 5.0)

        # 2. Second run: cooling (-1.0) makes it 4.0. Empty input.
        with open(self.input_file, 'w') as f:
            f.write("\n")

        # run_batch currently returns early if no dna_list, so we must provide at least one
        # but if we provide same dna, it's a dedupe hit.
        # Let's check how cooling is applied. It's applied if dna_list is non-empty.
        with open(self.input_file, 'w') as f:
            f.write("VOL05000750712\n") # Dedupe hit

        run_batch()

        with open(self.state_file, 'r') as f:
            state = json.load(f)
        # Cooling applied: 5.0 -> 4.0. No heat gain because it was dedupe hit.
        self.assertEqual(state['system_heat'], 4.0)

    def test_clarity_penalty(self):
        # 1. Set heat to 5.0
        with open(self.state_file, 'w') as f:
            json.dump({"system_heat": 6.0}, f) # 6.0 - 1.0 (cooling) = 5.0

        dna_cla = "CLAZN0900015"
        with open(self.input_file, 'w') as f:
            f.write(dna_cla + "\n")

        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)

        # Penalty = int(5.0) = 5
        # noise_floor.value: 90 -> 90 - 5 = 85
        # thd: 15 -> 15 + (5 * 10) = 65
        parsed = data[0]['parsed']
        self.assertEqual(parsed['noise_floor']['value'], 85)
        self.assertEqual(parsed['thd'], 65)

    def test_clarity_refusal(self):
        # 1. Set heat to 12.0
        with open(self.state_file, 'w') as f:
            json.dump({"system_heat": 12.0}, f) # 12.0 - 1.0 = 11.0

        dna_cla = "CLAZN0900015"
        with open(self.input_file, 'w') as f:
            f.write(dna_cla + "\n")

        run_batch() # Should not raise ThermalOverloadError but record it in output

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)

        self.assertIn("too high for Clarity", data[0]['error'])

        with open(os.path.join(self.data_dir, 'processed_ledger.json'), 'r') as f:
            ledger = json.load(f)
        self.assertTrue(ledger[dna_cla]['terminal_outcome'].startswith("error"))

if __name__ == '__main__':
    unittest.main()
