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

        # Mock Volume rule
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume", "prefix": "VOL",
                "subvars": {"amp": {"description": "amp", "min": 0, "max": 999, "pad": 3}}
            }, f)

        # Mock Clarity rule
        with open(os.path.join(self.rules_dir, 'rules_Clarity.json'), 'w') as f:
            json.dump({
                "variable": "Clarity", "prefix": "CLA",
                "subvars": {
                    "noise_floor": {"description": "nf", "min": 0, "max": 99, "pad": 2},
                    "thd": {"description": "thd", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_thermal_accumulation_and_dissipation(self):
        """Verify heat gain from VOL and passive dissipation."""
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')

        # Batch 1: VOL500 -> 5.0 heat.
        # Start of batch: 0.0 - 0.5 (min 0) = 0.0.
        # End of batch: 0.0 + 5.0 = 5.0.
        with open(input_file, 'w') as f:
            f.write("VOL500\n")
        run_batch()

        state_path = os.path.join(self.data_dir, 'system_state.json')
        with open(state_path, 'r') as f:
            state = json.load(f)
            self.assertEqual(state['system_heat'], 5.0)

        # Batch 2: Empty or new VOL.
        # Start of batch: 5.0 - 0.5 = 4.5.
        # VOL100 -> +1.0.
        # End of batch: 4.5 + 1.0 = 5.5.
        with open(input_file, 'w') as f:
            f.write("VOL100\n")
        run_batch()

        with open(state_path, 'r') as f:
            state = json.load(f)
            self.assertEqual(state['system_heat'], 5.5)

    def test_fatigue_penalties(self):
        """Verify CLA DNA is penalized by system heat."""
        state_path = os.path.join(self.data_dir, 'system_state.json')
        with open(state_path, 'w') as f:
            json.dump({"system_heat": 6.0}, f)

        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        # Start of batch: 6.0 - 0.5 = 5.5.
        # CLA05100: noise_floor=5, thd=100.
        # Penalty (heat=5.5):
        # noise_floor += int(5.5) = 5+5 = 10.
        # thd += int(5.5)*10 = 100+50 = 150.
        with open(input_file, 'w') as f:
            f.write("CLA05100\n")
        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)
            parsed = data[0]['parsed']
            self.assertEqual(parsed['noise_floor'], 10)
            self.assertEqual(parsed['thd'], 150)

    def test_thermal_overload_refusal(self):
        """Verify batch is refused if heat > 10.0."""
        state_path = os.path.join(self.data_dir, 'system_state.json')
        with open(state_path, 'w') as f:
            json.dump({"system_heat": 11.0}, f)

        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(input_file, 'w') as f:
            f.write("VOL100\n")

        # Start of batch: 11.0 - 0.5 = 10.5. 10.5 > 10.0 -> Refusal.
        with self.assertRaises(ThermalOverloadError):
            run_batch()

if __name__ == '__main__':
    unittest.main()
