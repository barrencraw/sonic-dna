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

        # Mock Volume and Clarity rules
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "amp": {"min": 0, "max": 1000, "pad": 4, "description": "amp"}
                }
            }, f)

        with open(os.path.join(self.rules_dir, 'rules_Clarity.json'), 'w') as f:
            json.dump({
                "variable": "Clarity",
                "prefix": "CLA",
                "subvars": {
                    "noise_floor": {"min": 0, "max": 120, "pad": 3, "sign": "N", "description": "noise"}
                }
            }, f)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.state_file = os.path.join(self.data_dir, 'system_state.json')

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation(self):
        # VOL0500 should add 5.0 heat (500/100)
        # But wait, there is a natural cooling of -1.0 at start of batch.
        # Initial heat 0 -> -1.0 -> 0.0
        # Then VOL0500 -> 5.0
        with open(self.input_file, 'w') as f:
            f.write("VOL0500\n")

        run_batch(data_dir=self.test_dir)

        with open(self.state_file, 'r') as f:
            state = json.load(f)
            self.assertEqual(state['system_heat'], 5.0)

    def test_clarity_penalty(self):
        # Set initial heat to 5.0
        with open(self.state_file, 'w') as f:
            json.dump({"system_heat": 5.0}, f)

        # Batch start: 5.0 - 1.0 = 4.0
        # CLA N090
        # Penalty: noise floor gets higher (less negative) by int(heat) = 4
        # New noise floor = 90 - 4 = 86
        with open(self.input_file, 'w') as f:
            f.write("CLAN090\n")

        run_batch(data_dir=self.test_dir)

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)
            # Resulting value for noise_floor.value should be 86
            self.assertEqual(data[0]['parsed']['noise_floor']['value'], 86)
            self.assertIn("CONSEQUENCE_APPLIED", data[0]['consequence'])

    def test_thermal_refusal(self):
        # Set initial heat to 12.0
        with open(self.state_file, 'w') as f:
            json.dump({"system_heat": 12.0}, f)

        # Batch start: 12.0 - 1.0 = 11.0
        # CLA should be refused (> 10.0)
        with open(self.input_file, 'w') as f:
            f.write("CLAN090\n")

        run_batch(data_dir=self.test_dir)

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)
            self.assertIn("Thermal overload", data[0]['error'])
            self.assertIn("REFUSAL_REASON", data[0]['error'])

    def test_natural_cooling_only(self):
        # Set initial heat to 5.0
        with open(self.state_file, 'w') as f:
            json.dump({"system_heat": 5.0}, f)

        # Empty input file should NOT run batch normally, but main() handles it
        # Actually main() returns early if no dna_list
        # But we want to test that heat decays even if we just "check" and find no work?
        # My implementation does: system_heat = max(0.0, system_heat - 1.0) if dna_list is not empty.

        with open(self.input_file, 'w') as f:
            f.write("\n") # Empty lines are skipped

        run_batch(data_dir=self.test_dir)

        # Since dna_list was empty, main returned early.
        with open(self.state_file, 'r') as f:
            state = json.load(f)
            self.assertEqual(state['system_heat'], 5.0) # No change if truly empty

        # If we have a DNA that is already in ledger, it should still cool
        ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')
        with open(ledger_path, 'w') as f:
            json.dump({"VOL0000": {"terminal_outcome": "SUCCESS"}}, f)

        with open(self.input_file, 'w') as f:
            f.write("VOL0000\n")

        run_batch(data_dir=self.test_dir)

        with open(self.state_file, 'r') as f:
            state = json.load(f)
            # 5.0 -> 4.0 because dna_list was not empty (it had 1 skipped item)
            self.assertEqual(state['system_heat'], 4.0)

if __name__ == '__main__':
    unittest.main()
