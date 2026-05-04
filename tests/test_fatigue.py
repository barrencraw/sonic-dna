import unittest
import os
import shutil
import tempfile
import json
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

        # Create Rule Files
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume", "prefix": "VOL",
                "subvars": {"amp": {"min": 0, "max": 1000, "pad": 4, "description": "amp"}}
            }, f)
        with open(os.path.join(self.rules_dir, 'rules_Clarity.json'), 'w') as f:
            json.dump({
                "variable": "Clarity", "prefix": "CLA",
                "subvars": {
                    "noise_floor": {"min": 0, "max": 120, "pad": 3, "sign": "N", "description": "noise"},
                    "thd": {"min": 0, "max": 1000, "pad": 4, "description": "thd"}
                }
            }, f)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation_and_penalty(self):
        """VOL strings increase heat, which penalizes CLA strings."""
        # VOL with amp 500 (5.0 heat units)
        # then CLA with noise N090 and thd 0010
        with open(self.input_file, 'w') as f:
            f.write("VOL0500\n")
            f.write("CLAN0900010\n")

        run_batch(data_dir=self.data_dir)

        # Check state
        state_path = os.path.join(self.data_dir, 'system_state.json')
        with open(state_path, 'r') as f:
            state = json.load(f)
            # 0.0 - 0.5 (passive) + 5.0 (VOL) = 4.5
            # WAIT: In the test, run_batch is called once.
            # If system_state.json doesn't exist, it starts at 0.0.
            # Then it does max(0.0, 0.0 - 0.5) = 0.0.
            # Then it processes VOL0500: 0.0 + 5.0 = 5.0.
            self.assertEqual(state['system_heat'], 5.0)

        # Check output
        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)
            # Find Clarity entry
            cla_entry = next(e for e in data if e.get('rule') == 'Clarity')
            # Penalty for 5.0 heat is floor(5.0) = 5
            # Noise: 90 - 5 = 85
            # THD: 10 + (5 * 10) = 60
            self.assertEqual(cla_entry['parsed']['noise_floor']['value'], 85)
            self.assertEqual(cla_entry['parsed']['thd'], 60)

    def test_thermal_overload_refusal(self):
        """Heat > 10.0 should stop processing."""
        # Initial heat 9.5
        state_path = os.path.join(self.data_dir, 'system_state.json')
        with open(state_path, 'w') as f:
            json.dump({'system_heat': 9.5}, f)

        # Batch starts: 9.5 - 0.5 = 9.0
        # Process VOL0200 (+2.0) -> 11.0
        # Next item should be refused
        with open(self.input_file, 'w') as f:
            f.write("VOL0200\n")
            f.write("VOL0100\n")

        run_batch(data_dir=self.data_dir)

        with open(state_path, 'r') as f:
            state = json.load(f)
            self.assertEqual(state['system_heat'], 11.0)

        ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')
        with open(ledger_path, 'r') as f:
            ledger = json.load(f)
            self.assertIn("VOL0200", ledger)
            self.assertNotIn("VOL0100", ledger)

if __name__ == '__main__':
    unittest.main()
