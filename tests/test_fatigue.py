import os
import json
import shutil
import unittest
from utils.dna_ui import main as run_batch, ThermalOverloadError

class TestFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.state_path = os.path.join(self.data_folder, 'system_state.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        # Backup existing data
        self.backup_folder = os.path.join(self.project_root, 'data_backup_fatigue')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation(self):
        # VOL with amp 500 should add 0.1 + (500/500) = 1.1 heat.
        # But passive cooling of 1.0 happens at start of main.
        # Initial heat 0.0 -> cooling (0.0) -> add 1.1 -> 1.1.
        dna = "VOL05000500510"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertAlmostEqual(state['system_heat'], 1.1)

    def test_thermal_noise(self):
        # Set heat to 4.9.
        # Next sequence (non-VOL) adds 0.2 -> 5.1. Noise should trigger.
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 5.9}, f) # Already hot (after 1.0 cooling it will be 4.9)

        dna = "VOL05000500510" # adds 1.1 -> 4.9 + 1.1 = 6.0
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        self.assertTrue(data[0]['thermal_noise'])
        # Original amp was 500, with 0.9 noise it should be 450
        self.assertEqual(data[0]['parsed']['amp'], 450)

    def test_thermal_overload(self):
        # Set heat to 10.0 (after 1.0 cooling = 9.0)
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 10.0}, f)

        # This adds 1.1 -> 9.0 + 1.1 = 10.1 (> 10.0)
        dna = "VOL05000500510"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

    def test_cooling_cycle(self):
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 2.0}, f)

        # Passive cooling 1.0 -> 1.0.
        # VOL amp 050 (< 100) -> dissipation 0.5. 1.0 - 0.5 = 0.5.
        dna = "VOL00500500510"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertAlmostEqual(state['system_heat'], 0.5)

    def test_idempotency_no_heat_gain(self):
        dna = "VOL05000500510"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch() # Heat becomes 1.1

        with open(self.state_path, 'r') as f:
            heat1 = json.load(f)['system_heat']

        run_batch() # Already in ledger. Passive cooling 1.0. No heat gain. 1.1 - 1.0 = 0.1

        with open(self.state_path, 'r') as f:
            heat2 = json.load(f)['system_heat']

        self.assertAlmostEqual(heat2, max(0.0, heat1 - 1.0))

if __name__ == '__main__':
    unittest.main()
