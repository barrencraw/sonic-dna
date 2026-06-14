import os
import json
import shutil
import unittest
import time
from utils.dna_ui import main as run_batch, ThermalOverloadError, MAX_HEAT, HEAT_PER_ITEM

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.ledger_path = os.path.join(self.data_folder, 'ledger.json')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')

        # Backup
        self.backup_folder = os.path.join(self.project_root, 'data_backup_thermal')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation(self):
        # Process 3 items
        dnas = ["VOL08900750712", "VOL00000000000", "VOL11111111111"]
        with open(self.input_file, 'w') as f:
            for d in dnas:
                f.write(d + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        self.assertGreaterEqual(state['system_heat'], 3.0)
        self.assertLess(state['system_heat'], 4.0) # Should be exactly 3 minus tiny cooling

    def test_thermal_refusal(self):
        # Exceed MAX_HEAT
        num_items = int(MAX_HEAT / HEAT_PER_ITEM) + 1
        dnas = [f"VOL{str(i).zfill(11)}" for i in range(num_items)]

        with open(self.input_file, 'w') as f:
            for d in dnas:
                f.write(d + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

    def test_cooling(self):
        # Heat it up
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state1 = json.load(f)
        heat1 = state1['system_heat']
        self.assertGreater(heat1, 0)

        # Wait for cooling
        time.sleep(1.1)

        # Run again (even if no new DNA, cooling should apply)
        # But run_batch returns early if no DNA and no change in heat.
        # We need to provide at least one DNA to trigger the logic, even if already processed.
        run_batch()

        with open(self.ledger_path, 'r') as f:
            state2 = json.load(f)
        heat2 = state2['system_heat']

        self.assertLess(heat2, heat1)

if __name__ == '__main__':
    unittest.main()
