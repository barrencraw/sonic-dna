import unittest
import os
import shutil
import tempfile
import json
from utils.dna_ui import main as run_batch, ThermalOverloadError

class TestFatigue(unittest.TestCase):
    def setUp(self):
        # Create a temporary project structure
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
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        # Mock Clarity rule
        with open(os.path.join(self.rules_dir, 'rules_Clarity.json'), 'w') as f:
            json.dump({
                "variable": "Clarity",
                "prefix": "CLA",
                "subvars": {
                    "spectral_flat": {"class": "Z-A", "description": "flatness"},
                    "noise_floor": {"min": 0, "max": 120, "pad": 3, "sign": "N", "description": "noise"},
                    "thd": {"min": 0, "max": 1000, "pad": 4, "description": "thd"}
                }
            }, f)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation(self):
        """Verify that processing Volume DNA increases system heat."""
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        # VOL500 -> level 500 -> 5.0 heat
        with open(input_file, 'w') as f:
            f.write("VOL500\n")

        run_batch(data_dir=self.test_dir)

        state_path = os.path.join(self.data_dir, 'system_state.json')
        with open(state_path, 'r') as f:
            state = json.load(f)
            # Heat starts at 0.0, non-empty list causes -1.0 cooling, but clipped at 0.0.
            # Then VOL500 adds 5.0.
            self.assertEqual(state['system_heat'], 5.0)

    def test_clarity_penalties(self):
        """Verify that Clarity parsing is penalized by system heat."""
        # 1. Add heat
        state_path = os.path.join(self.data_dir, 'system_state.json')
        with open(state_path, 'w') as f:
            json.dump({"system_heat": 5.0}, f)

        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        # CLAZN0900015
        with open(input_file, 'w') as f:
            f.write("CLAZN0900015\n")

        run_batch(data_dir=self.test_dir)

        # Heat was 5.0. Non-empty batch -> cooling -> 4.0.
        # noise_floor 90 - 4 = 86
        # thd 15 + (4 * 10) = 55

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)
            parsed = data[0]['parsed']
            self.assertEqual(parsed['noise_floor']['value'], 86)
            self.assertEqual(parsed['thd'], 55)

    def test_thermal_overload_refusal(self):
        """Verify that Clarity parsing is refused if heat > 10.0."""
        state_path = os.path.join(self.data_dir, 'system_state.json')
        with open(state_path, 'w') as f:
            json.dump({"system_heat": 12.0}, f)

        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(input_file, 'w') as f:
            f.write("CLAZN0900015\n")

        # run_batch will catch the error internally for the item
        run_batch(data_dir=self.test_dir)

        # Check that it's NOT in the ledger and NOT in the output
        ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')
        # In this specific case, NO_NEW_DNA might not even create the ledger file if it's the first run
        if os.path.exists(ledger_path):
            with open(ledger_path, 'r') as f:
                ledger = json.load(f)
                self.assertNotIn("CLAZN0900015", ledger)

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        if os.path.exists(json_out):
            with open(json_out, 'r') as f:
                data = json.load(f)
                self.assertEqual(len(data), 0)

if __name__ == '__main__':
    unittest.main()
