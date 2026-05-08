import os
import json
import shutil
import unittest
import time
from utils.dna_ui import main as run_batch, ThermalOverloadError

class TestFatigue(unittest.TestCase):
    def setUp(self):
        # Setup paths
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.state_path = os.path.join(self.data_folder, 'system_state.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        # Backup existing data if any
        self.backup_folder = os.path.join(self.project_root, 'data_backup_fatigue')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        # Ensure clean state for test
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

    def tearDown(self):
        # Restore backup
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_thermal_gain_and_dissipation(self):
        # 1. Process Volume DNA to increase heat
        # Initial heat = 0.0
        # Passive dissipation = -0.5 (but min 0) -> heat = 0.0
        # amp = 500 (50.0%) -> heat gain = 5.0
        # Total heat should be 5.0
        dna_vol = "VOL05000750712"
        with open(self.input_file, 'w') as f:
            f.write(dna_vol + "\n")

        run_batch()

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 5.0)

        # 2. Run another batch with no new DNA to see dissipation
        # Previous heat = 5.0
        # Passive dissipation = -0.5
        # Total heat should be 4.5
        os.remove(self.input_file)
        with open(self.input_file, 'w') as f:
            pass

        run_batch()

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 4.5)

    def test_clarity_penalties(self):
        # 1. Set heat to 5.5
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 5.5}, f)

        # 2. Process Clarity DNA
        # CLA prefix + spectral flatness (Z) + noise floor (N090) + THD (0015)
        dna_cla = "CLAZN0900015"
        with open(self.input_file, 'w') as f:
            f.write(dna_cla + "\n")

        # Passive dissipation = -0.5 -> Current heat = 5.0
        # Penalty = int(5.0) = 5
        # noise_floor: 90 - 5 = 85
        # thd: 15 + 5 * 10 = 65

        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        parsed = data[0]['parsed']
        self.assertEqual(parsed['noise_floor']['value'], 85)
        self.assertEqual(parsed['thd'], 65)
        self.assertIn("CONSEQUENCE_APPLIED", data[0]['system_feedback'][0])

    def test_thermal_overload_refusal(self):
        # 1. Set heat to 10.5
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 10.5}, f)

        # 2. Process any DNA
        dna = "VOL01000750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # Passive dissipation = -0.5 -> Current heat = 10.0
        # 10.0 is not > 10.0, so it should still process it.
        run_batch()

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 11.0) # 10.0 + 1.0

        # 3. Next one should refuse
        # Current heat = 11.0
        # Passive dissipation = -0.5 -> Current heat = 10.5
        # 10.5 > 10.0 -> REFUSAL
        dna2 = "VOL01000750713"
        with open(self.input_file, 'w') as f:
            f.write(dna2 + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

if __name__ == '__main__':
    unittest.main()
