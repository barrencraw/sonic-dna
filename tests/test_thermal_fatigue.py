import os
import json
import shutil
import unittest
import tempfile
from utils.dna_ui import main as run_batch, ThermalOverloadError

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
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
        self.json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')

        # Mock a Volume rule
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation(self):
        # DNA for Volume 500 -> heat gain 0.1 + 500/500 = 1.1
        dna = "VOL500"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.state_file, 'r') as f:
            state = json.load(f)
            self.assertAlmostEqual(state['system_heat'], 1.1)

    def test_thermal_noise_application(self):
        # Initial heat 7.5 (above threshold 7.0)
        with open(self.state_file, 'w') as f:
            json.dump({'system_heat': 7.5}, f)

        dna = "VOL500"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.json_out, 'r') as f:
            data = json.load(f)
            # Normal level is 500. With 0.9 noise factor, it should be 450.
            self.assertEqual(data[0]['parsed']['level'], 450)

    def test_thermal_overload_refusal(self):
        # Initial heat 9.5. Adding VOL500 (gain 1.1) will reach 10.6 (> 10.0)
        with open(self.state_file, 'w') as f:
            json.dump({'system_heat': 9.5}, f)

        dna = "VOL500"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # Verify heat was still incremented and persisted
        with open(self.state_file, 'r') as f:
            state = json.load(f)
            self.assertAlmostEqual(state['system_heat'], 10.6)

        # Verify nothing added to output for the failed item
        with open(self.json_out, 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data), 0)

if __name__ == '__main__':
    unittest.main()
