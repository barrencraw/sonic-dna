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
        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)

        # Symlink rules
        self.project_root = os.getcwd()
        os.symlink(os.path.join(self.project_root, 'rules'), os.path.join(self.test_dir, 'rules'))

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.state_file = os.path.join(self.data_dir, 'system_state.json')
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def write_dna(self, dna_list):
        with open(self.input_file, 'w', encoding='utf-8') as f:
            for dna in dna_list:
                f.write(dna + '\n')

    def get_heat(self):
        if not os.path.exists(self.state_file):
            return 0.0
        with open(self.state_file, 'r') as f:
            return json.load(f).get("system_heat", 0.0)

    def test_heat_accumulation(self):
        # Start: 0.0. Passive dissipation: max(0.0, 0.0 - 0.1) = 0.0
        # VOL amp=500 -> heat_gain = 0.1 + 500/500 = 1.1
        # Total expected heat: 0.0 + 1.1 = 1.1
        self.write_dna(["VOL05000500512"])
        run_batch()
        self.assertAlmostEqual(self.get_heat(), 1.1)

    def test_cooling_cycle(self):
        # Set initial heat
        with open(self.state_file, 'w') as f:
            json.dump({"system_heat": 2.0}, f)

        # VOL amp=0050 -> cooling cycle -> heat_gain = -0.5
        # Passive dissipation = -0.1
        # Total expected: 2.0 - 0.1 - 0.5 = 1.4
        self.write_dna(["VOL00500500512"])
        run_batch()
        self.assertAlmostEqual(self.get_heat(), 1.4)

    def test_thermal_noise(self):
        # Set heat to 4.5
        with open(self.state_file, 'w') as f:
            json.dump({"system_heat": 4.5}, f)

        # VOL amp=500 -> gain 1.1. Total 5.6 (with dissipation: 4.5 - 0.1 + 1.1 = 5.5)
        # Wait, dissipation happens at START.
        # Start: 4.5. Dissipate: 4.4.
        # Process VOL0500: gain 1.1. Current heat: 5.5.
        # Since 5.5 > 5.0, noise should be applied to THIS sequence?
        # Code: if system_heat + heat_gain > 5.0: apply noise
        self.write_dna(["VOL05000500512"])
        run_batch()

        parsed_path = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(parsed_path, 'r') as f:
            data = json.load(f)
            # Original amp=500, noisy should be 500 * 0.9 = 450
            self.assertEqual(data[0]['parsed']['amp'], 450)

    def test_thermal_overload(self):
        # Set heat to 9.5
        with open(self.state_file, 'w') as f:
            json.dump({"system_heat": 9.5}, f)

        # Start: 9.5. Dissipate: 9.4.
        # VOL0500: gain 1.1. 9.4 + 1.1 = 10.5 > 10.0 -> Overload
        self.write_dna(["VOL05000500512"])
        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # Heat should still be saved (9.4)
        self.assertAlmostEqual(self.get_heat(), 9.4)

    def test_idempotency_no_heat(self):
        self.write_dna(["VOL05000500512"])
        run_batch()
        # Heat after first run should be 1.1
        self.assertAlmostEqual(self.get_heat(), 1.1)

        # Run again with same DNA
        run_batch()
        # Passive dissipation: 1.1 - 0.1 = 1.0
        # Idempotency: no heat gain.
        self.assertAlmostEqual(self.get_heat(), 1.0)

    def test_multiple_sequences_accumulation(self):
        # Start: 0.0. Dissipate: 0.0.
        # 1. VOL0500: gain 1.1. Heat: 1.1.
        # 2. VOL0500: gain 1.1. Heat: 2.2.
        self.write_dna(["VOL05000500512", "VOL05010500512"]) # slightly different to avoid dedupe if I used same
        run_batch()
        self.assertAlmostEqual(self.get_heat(), 2.202, places=3) # 0.1 + 500/500 + 0.1 + 501/500 = 1.1 + 1.102 = 2.202

if __name__ == '__main__':
    unittest.main()
