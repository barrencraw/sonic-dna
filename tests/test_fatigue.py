import os
import json
import shutil
import unittest
import time
from utils.dna_ui import main as run_batch, ThermalOverloadError

class TestThermalFatigue(unittest.TestCase):
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

        # Initialize empty ledger and state
        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)
        # We start with heat 0.1 because dissipation -0.1 happens first
        with open(self.state_path, 'w') as f:
            json.dump({'system_heat': 0.1}, f)

    def tearDown(self):
        # Restore backup
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation(self):
        # Initial heat = 0.1
        # Dissipation = -0.1 -> heat = 0.0
        # VOL0500... -> amp=500 -> heat_gain = 0.1 + (500/500) = 1.1
        # Net heat = 1.1
        dna = "VOL05000500510"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 1.1)

    def test_thermal_noise(self):
        # Initial heat = 0.1
        # Each batch: Dissipation -0.1, Gain +1.1 -> Net +1.0
        # 5 batches -> 0.1 + 5.0 = 5.1
        dna_template = "VOL050005005{id:02}"

        for i in range(5):
            with open(self.input_file, 'w') as f:
                f.write(dna_template.format(id=i) + "\n")
            run_batch()

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 5.1)

        # Next batch triggers noise because 5.1 - 0.1 + 1.1 = 6.1 > 5.0
        dna_noise = dna_template.format(id=5)
        with open(self.input_file, 'w') as f:
            f.write(dna_noise + "\n")
        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        # Find the entry for dna_noise
        entry = next(e for e in data if e['dna'] == dna_noise)
        # amp was 500, with 0.9 noise it should be 450
        self.assertEqual(entry['parsed']['amp'], 450.0)

    def test_thermal_overload(self):
        # Set heat high
        with open(self.state_path, 'w') as f:
            json.dump({'system_heat': 9.5}, f)

        # 9.5 - 0.1 (dissipation) + 1.1 (gain) = 10.5 > 10.0 -> Overload
        dna = "VOL05000500510"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # Verify heat saved after dissipation
        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 9.4)

    def test_cooling_cycle(self):
        # Set heat high
        with open(self.state_path, 'w') as f:
            json.dump({'system_heat': 5.0}, f)

        # amp < 100 -> cooling
        dna = "VOL00500500510" # amp=50
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        # 5.0 - 0.1 (passive) - 0.5 (cooling) = 4.4
        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 4.4)

if __name__ == '__main__':
    unittest.main()
