import unittest
import os
import json
import shutil
import tempfile
from utils.dna_ui import main as dna_main, ThermalOverloadError

class TestFatigueSystem(unittest.TestCase):
    def setUp(self):
        # Create a temporary sandbox for data
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)

        # Link rules directory
        self.project_root = os.getcwd()
        os.symlink(os.path.join(self.project_root, 'rules'), os.path.join(self.test_dir, 'rules'))

        # Change working directory to test sandbox
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.state_file = os.path.join(self.data_dir, 'system_state.json')

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation_and_dissipation(self):
        # Initial heat should be 0.0
        # Passive cooling = -0.5 -> max(0, -0.5) = 0
        # VOL08900750712 -> amp=0890 (89.0) -> gain = 0.1 + (890/500) = 0.1 + 1.78 = 1.88
        # Total after 1: 0.0 + 1.88 = 1.88

        with open(self.input_file, 'w') as f:
            f.write("VOL08900750712\n")

        dna_main()

        with open(self.state_file, 'r') as f:
            state = json.load(f)

        self.assertEqual(state['system_heat'], 1.88)

    def test_thermal_noise_application(self):
        # Set heat to 6.0
        with open(self.state_file, 'w') as f:
            json.dump({"system_heat": 6.0}, f)

        # amp=0500 -> 50.0%
        with open(self.input_file, 'w') as f:
            f.write("VOL05000750712\n")

        dna_main()

        # Check parsed output for noise
        # 500 * 0.9 = 450
        output_json = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(output_json, 'r') as f:
            parsed = json.load(f)

        self.assertEqual(parsed[0]['parsed']['amp'], 450.0)

    def test_thermal_overload_refusal(self):
        # Set heat to 11.0
        with open(self.state_file, 'w') as f:
            json.dump({"system_heat": 11.0}, f)

        with open(self.input_file, 'w') as f:
            f.write("VOL05000750712\n")

        with self.assertRaises(ThermalOverloadError):
            dna_main()

    def test_idempotency_maintained(self):
        with open(self.input_file, 'w') as f:
            f.write("VOL05000750712\n")

        dna_main() # Heat: max(0, 0-0.5) + 0.1 + 500/500 = 1.1

        with open(self.state_file, 'r') as f:
            state1 = json.load(f)

        # Run again with same input (should dedupe)
        dna_main() # Passive cooling: 1.1 - 0.5 = 0.6

        with open(self.state_file, 'r') as f:
            state2 = json.load(f)

        self.assertEqual(state2['system_heat'], 0.6)

if __name__ == '__main__':
    unittest.main()
