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

        # Mock Volume and Clarity rules
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

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.state_file = os.path.join(self.data_dir, 'system_state.json')

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation_from_volume(self):
        """VOL0500... should add 500/100 = 5.0 heat. -1.0 cooling = 4.0 total."""
        with open(self.input_file, 'w') as f:
            f.write("VOL05000750712\n")

        run_batch()

        with open(self.state_file, 'r') as f:
            state = json.load(f)
            # Starting heat 0.0, cooling -1.0 (clamped to 0), +5.0 from VOL = 5.0
            self.assertEqual(state['system_heat'], 5.0)

    def test_clarity_penalty_at_medium_heat(self):
        """Heat at 5.0 should reduce Clarity noise floor by 5 and increase THD by 50."""
        # Pre-set heat to 6.0
        with open(self.state_file, 'w') as f:
            json.dump({"system_heat": 6.0}, f)

        # In batch: 6.0 - 1.0 (cooling) = 5.0 heat.
        with open(self.input_file, 'w') as f:
            f.write("CLAZN0900015\n")

        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)
            parsed = data[0]['parsed']
            # N090 -> 90 - 5 = 85 (N085)
            self.assertEqual(parsed['noise_floor']['value'], 85)
            # 0015 -> 15 + 50 = 65 (0065)
            self.assertEqual(parsed['thd'], 65)

    def test_clarity_refusal_at_high_heat(self):
        """Heat > 10.0 should refuse Clarity strings."""
        # Pre-set heat to 11.1
        with open(self.state_file, 'w') as f:
            json.dump({"system_heat": 11.1}, f)

        # In batch: 11.1 - 1.0 = 10.1 heat.
        with open(self.input_file, 'w') as f:
            f.write("CLAZN0900015\n")

        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)
            self.assertIn("REFUSAL_REASON", data[0]['error'])
            self.assertIn("10.1", data[0]['error'])

    def test_idempotency_and_cooling(self):
        """Repeated batches should apply cooling but not re-process DNA."""
        with open(self.state_file, 'w') as f:
            json.dump({"system_heat": 5.0}, f)

        # Batch 1: cooling -1.0 = 4.0. Empty input.
        with open(self.input_file, 'w') as f:
            pass
        run_batch()
        with open(self.state_file, 'r') as f:
            self.assertEqual(json.load(f)['system_heat'], 4.0)

        # Batch 2: cooling -1.0 = 3.0.
        run_batch()
        with open(self.state_file, 'r') as f:
            self.assertEqual(json.load(f)['system_heat'], 3.0)

if __name__ == '__main__':
    unittest.main()
