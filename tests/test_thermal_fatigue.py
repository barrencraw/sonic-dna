import unittest
import os
import json
import shutil
import tempfile
from utils.dna_ui import main as run_batch, ThermalOverloadError

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')
        self.state_path = os.path.join(self.data_dir, 'system_state.json')
        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        # Mock Volume rule
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "amp": {"description": "amp", "min": 0, "max": 1000, "pad": 4}
                }
            }, f)

        # Initialize state
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 0.0}, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation(self):
        """High amplitude sequences should increase heat."""
        # VOL1000 -> gain = 0.1 + (1000/500) = 2.1
        # Passive dissipation at start: max(0, 0.0 - 0.1) = 0.0
        # Total heat: 2.1
        with open(self.input_file, 'w') as f:
            f.write("VOL1000\n")

        run_batch()

        with open(self.state_path, 'r') as f:
            state = json.load(f)
            self.assertAlmostEqual(state['system_heat'], 2.1)

    def test_cooling_cycle(self):
        """Low amplitude sequences should reduce heat."""
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 5.0}, f)

        # Passive dissipation: -0.1
        # VOL0050 -> gain = -0.5
        # Net: 5.0 - 0.1 - 0.5 = 4.4
        with open(self.input_file, 'w') as f:
            f.write("VOL0050\n")

        run_batch()

        with open(self.state_path, 'r') as f:
            state = json.load(f)
            self.assertAlmostEqual(state['system_heat'], 4.4)

    def test_thermal_noise_threshold(self):
        """Heat > 7.0 should scale numeric values by 0.9."""
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 8.0}, f)

        # Passive dissipation: -0.1 -> 7.9
        # VOL0500 -> gain = 0.1 + 500/500 = 1.1 -> Total heat 9.0
        with open(self.input_file, 'w') as f:
            f.write("VOL0500\n")

        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)
            # Original amp 500 * 0.9 = 450
            self.assertEqual(data[0]['parsed']['amp'], 450.0)

    def test_thermal_overload_refusal(self):
        """Heat + gain > 10.0 should raise ThermalOverloadError."""
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 9.0}, f)

        # Passive dissipation: -0.1 -> 8.9
        # VOL1000 -> gain = 2.1 -> Total 11.0 (Overload)
        with open(self.input_file, 'w') as f:
            f.write("VOL1000\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # Verify heat was updated even on failure
        with open(self.state_path, 'r') as f:
            state = json.load(f)
            self.assertAlmostEqual(state['system_heat'], 11.0)

if __name__ == '__main__':
    unittest.main()
