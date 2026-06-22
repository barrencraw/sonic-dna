import os
import json
import shutil
import unittest
import time
from unittest.mock import patch
from utils.dna_ui import main as run_batch, MAX_HEAT, HEAT_PER_ITEM, COOLING_RATE_PER_SEC, ThermalOverloadError

class TestFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

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
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        self.assertEqual(state['system_heat'], HEAT_PER_ITEM)

    def test_cooling(self):
        dna1 = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna1 + "\n")

        # Mock time to control cooling
        start_time = 1000.0
        with patch('time.time', return_value=start_time):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], HEAT_PER_ITEM)

        # Advance time by 10 seconds
        dna2 = "VOL00000000000"
        with open(self.input_file, 'w') as f:
            f.write(dna2 + "\n")

        with patch('time.time', return_value=start_time + 10.0):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        expected_heat = (HEAT_PER_ITEM - (10.0 * COOLING_RATE_PER_SEC)) + HEAT_PER_ITEM
        self.assertAlmostEqual(state['system_heat'], expected_heat)

    def test_thermal_overload_refusal(self):
        # Generate enough DNA to exceed MAX_HEAT
        dnas = [f"VOL{str(i).zfill(11)}" for i in range(int(MAX_HEAT) + 1)]
        with open(self.input_file, 'w') as f:
            for dna in dnas:
                f.write(dna + "\n")

        # run_batch handles ThermalOverloadError internally and stops
        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # Should have stopped at exactly MAX_HEAT
        self.assertEqual(state['system_heat'], MAX_HEAT)
        self.assertEqual(len(state['ledger']), int(MAX_HEAT))

    def test_idempotency_does_not_increase_heat(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
        heat_after_first = state['system_heat']

        # Run again with same DNA
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # Mock time so no cooling occurs
        with patch('time.time', return_value=state['last_processed_timestamp']):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        self.assertEqual(state['system_heat'], heat_after_first)

if __name__ == '__main__':
    unittest.main()
