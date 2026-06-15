import os
import json
import shutil
import unittest
import time
from utils.dna_ui import main as run_batch, ThermalOverloadError, MAX_HEAT, HEAT_PER_ITEM

class TestFatigue(unittest.TestCase):
    def setUp(self):
        # Setup paths
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'ledger.json')

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

    def test_heat_accumulation(self):
        # DNA for Volume (prefix 'VOL')
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        self.assertEqual(state['system_heat'], HEAT_PER_ITEM)
        self.assertGreater(state['last_processed_timestamp'], 0)

    def test_thermal_overload_refusal(self):
        # Create a batch that exceeds MAX_HEAT
        count = int(MAX_HEAT / HEAT_PER_ITEM) + 1
        dnas = [f"VOL{i:011d}" for i in range(count)]

        with open(self.input_file, 'w') as f:
            for dna in dnas:
                f.write(dna + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # Verify ledger wasn't created or updated (since it failed before processing)
        if os.path.exists(self.ledger_path):
            with open(self.ledger_path, 'r') as f:
                state = json.load(f)
            self.assertEqual(state.get('system_heat', 0), 0)

    def test_cooling_behavior(self):
        # 1. Process one item to generate heat
        dna1 = "VOL00000000001"
        with open(self.input_file, 'w') as f:
            f.write(dna1 + "\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
        initial_heat = state['system_heat']
        self.assertEqual(initial_heat, HEAT_PER_ITEM)

        # 2. Artificially set the timestamp back in the past to simulate cooling
        state['last_processed_timestamp'] -= 100 # 100 seconds ago
        with open(self.ledger_path, 'w') as f:
            json.dump(state, f)

        # 3. Process another item
        dna2 = "VOL00000000002"
        with open(self.input_file, 'w') as f:
            f.write(dna2 + "\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # Expected heat = (initial_heat - (100 * COOLING_RATE)) + HEAT_PER_ITEM
        # COOLING_RATE = 0.01, so 100 * 0.01 = 1.0
        # Expected = (1.0 - 1.0) + 1.0 = 1.0
        self.assertAlmostEqual(state['system_heat'], 1.0)

if __name__ == '__main__':
    unittest.main()
