import os
import json
import shutil
import unittest
import tempfile
from utils.dna_ui import main as run_batch, Outcome

class TestFatigue(unittest.TestCase):
    def setUp(self):
        # Setup temporary test environment
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
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_dir, 'toSequence_parsed.json')

        # Create minimal rules for VOL and CLA
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

    def test_thermal_accumulation_and_cla_penalty(self):
        # 1. Add some heat with VOL
        # VOL0500 -> 5.0 heat
        with open(self.input_file, 'w') as f:
            f.write("VOL0500\n")

        run_batch()

        with open(self.state_file, 'r') as f:
            state = json.load(f)
            # 0.0 - 0.5 (cool, clamp 0) + 5.0 (VOL) = 5.0
            self.assertEqual(state['system_heat'], 5.0)

        # 2. Process CLA and check penalty
        # Heat is 5.0. Next batch starts with 5.0 - 0.5 = 4.5 cooling.
        # Penalty: noise_floor -4, THD +40
        with open(self.input_file, 'w') as f:
            f.write("CLAZN0900010\n")

        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)
            # Find the CLA entry
            cla_entry = next(e for e in data if e['dna'] == 'CLAZN0900010')
            self.assertEqual(cla_entry['parsed']['noise_floor']['value'], 86) # 90 - 4
            self.assertEqual(cla_entry['parsed']['thd'], 50) # 10 + 40
            self.assertIn("CONSEQUENCE_APPLIED", cla_entry)
            self.assertIn("Thermal noise penalty", cla_entry['CONSEQUENCE_APPLIED'])

    def test_thermal_overload_refusal(self):
        # 1. Ramp up heat beyond 10
        # Start heat at 11
        with open(self.state_file, 'w') as f:
            json.dump({"system_heat": 11.0}, f)

        # 2. Attempt CLA
        # Heat 11.0 - 0.5 (cooling) = 10.5 (> 10.0)
        with open(self.input_file, 'w') as f:
            f.write("CLAZN0900010\n")

        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)
            cla_entry = data[0]
            self.assertIn("REFUSAL_REASON", cla_entry)
            self.assertIn("Core temperature critical", cla_entry['REFUSAL_REASON'])
            self.assertIn("NEXT_ACTION_HINT", cla_entry)

        with open(self.ledger_file, 'r') as f:
            ledger = json.load(f)
            self.assertEqual(ledger['CLAZN0900010']['terminal_outcome'], Outcome.ERROR.name)

    def test_idempotency_no_double_heat(self):
        # Process VOL twice
        dna = "VOL0500"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()
        # 0.0 - 0.5 -> 0.0 + 5.0 = 5.0

        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()
        # Should be SKIPPED.
        # 5.0 - 0.5 = 4.5.

        with open(self.state_file, 'r') as f:
            state = json.load(f)
            self.assertEqual(state['system_heat'], 4.5)

if __name__ == '__main__':
    unittest.main()
