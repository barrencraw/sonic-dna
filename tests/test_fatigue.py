import os
import json
import shutil
import unittest
import time
from utils.dna_ui import main as run_batch, MAX_HEAT, HEAT_PER_ITEM

class TestFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        # Backup
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

    def test_heat_accumulation_and_lockout(self):
        # Create enough DNA to exceed MAX_HEAT
        count = int(MAX_HEAT / HEAT_PER_ITEM) + 2
        dnas = [f"VOL{str(i).zfill(11)}" for i in range(count)]

        with open(self.input_file, 'w') as f:
            for d in dnas:
                f.write(d + "\n")

        # Run batch - should hit ThermalOverloadError and stop
        run_batch()

        # Check ledger
        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        processed_count = len(state['ledger'])
        self.assertLess(processed_count, count, "Should have stopped before processing all items")
        self.assertAlmostEqual(state['system_heat'], processed_count * HEAT_PER_ITEM)
        self.assertGreater(state['system_heat'], MAX_HEAT - HEAT_PER_ITEM)

    def test_cooling_over_time(self):
        # 1. Heat up the system
        dna = "VOL00000000001"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state1 = json.load(f)
        heat1 = state1['system_heat']
        self.assertEqual(heat1, HEAT_PER_ITEM)

        # 2. Wait a bit (simulate cooling via manual timestamp manipulation for speed)
        # We'll set last_processed_timestamp to 100 seconds ago
        state1['last_processed_timestamp'] = time.time() - 100
        with open(self.ledger_path, 'w') as f:
            json.dump(state1, f)

        # 3. Run again with new DNA
        dna2 = "VOL00000000002"
        with open(self.input_file, 'w') as f:
            f.write(dna2 + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state2 = json.load(f)

        # Expected cooling: 100 sec * 0.01 = 1.0
        # Heat after cooling: 1.0 - 1.0 = 0.0
        # Heat after processing dna2: 0.0 + 1.0 = 1.0
        self.assertAlmostEqual(state2['system_heat'], HEAT_PER_ITEM)

if __name__ == '__main__':
    unittest.main()
