import os
import json
import shutil
import unittest
import time
from utils.dna_ui import main as run_batch, MAX_HEAT, HEAT_PER_ITEM

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        # Setup paths
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'ledger.json')

        # Backup existing data if any
        self.backup_folder = os.path.join(self.project_root, 'data_backup')
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

    def test_heat_accumulation(self):
        # Each item adds HEAT_PER_ITEM (1.0)
        # Process 3 items
        dna_list = ["VOL00000000001", "VOL00000000002", "VOL00000000003"]
        with open(self.input_file, 'w') as f:
            for dna in dna_list:
                f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # 3.0 heat (minus negligible cooling during execution)
        self.assertGreaterEqual(state['system_heat'], 2.9)
        self.assertLessEqual(state['system_heat'], 3.0)
        self.assertEqual(len(state['ledger']), 3)

    def test_thermal_overload_lockout(self):
        # MAX_HEAT is 10.0. Process 12 items.
        # It should process 10 and then stop.
        dna_list = [f"VOL{i:011d}" for i in range(12)]
        with open(self.input_file, 'w') as f:
            for dna in dna_list:
                f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # Should have stopped at MAX_HEAT
        self.assertEqual(len(state['ledger']), int(MAX_HEAT / HEAT_PER_ITEM))
        self.assertGreaterEqual(state['system_heat'], MAX_HEAT - 0.1)

    def test_deterministic_cooling(self):
        # Process 1 item to get 1.0 heat
        with open(self.input_file, 'w') as f:
            f.write("VOL00000000001\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
        initial_heat = state['system_heat']
        self.assertGreaterEqual(initial_heat, 0.9)

        # Wait 2 seconds. COOLING_RATE_PER_SEC is 0.01.
        # Should cool by 0.02.
        time.sleep(2.1)

        # Run batch again with new item
        with open(self.input_file, 'w') as f:
            f.write("VOL00000000002\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # Heat should be (initial_heat - 0.02 + 1.0)
        # We check that it cooled.
        self.assertLess(state['system_heat'], initial_heat + 1.0)
        # Specifically, it should be around (1.0 - 0.02 + 1.0) = 1.98
        self.assertLess(state['system_heat'], 1.99)

if __name__ == '__main__':
    unittest.main()
