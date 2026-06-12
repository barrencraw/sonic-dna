import os
import json
import shutil
import unittest
import time
from unittest.mock import patch
from utils.dna_ui import main as run_batch, MAX_HEAT, HEAT_PER_ITEM, ThermalOverloadError

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'ledger.json')

        # Backup existing data
        self.backup_folder = os.path.join(self.project_root, 'data_backup_thermal')
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

    def test_heat_increase(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        self.assertAlmostEqual(state["system_heat"], HEAT_PER_ITEM)
        self.assertIn(dna, state["ledger"])

    def test_thermal_overload_refusal(self):
        # We need more than MAX_HEAT / HEAT_PER_ITEM items
        num_items = int(MAX_HEAT / HEAT_PER_ITEM) + 1
        dnas = [f"VOL{str(i).zfill(4)}0750712" for i in range(num_items)]

        with open(self.input_file, 'w') as f:
            for dna in dnas:
                f.write(dna + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # Should have processed MAX_HEAT / HEAT_PER_ITEM items
        self.assertEqual(len(state["ledger"]), int(MAX_HEAT / HEAT_PER_ITEM))
        self.assertAlmostEqual(state["system_heat"], MAX_HEAT)

    def test_cooling_over_time(self):
        dna1 = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna1 + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
        initial_heat = state["system_heat"]
        self.assertAlmostEqual(initial_heat, HEAT_PER_ITEM)

        # Mock time to simulate passing of 50 seconds
        # COOLING_RATE_PER_SEC = 0.01 -> 50 * 0.01 = 0.5 cooling
        with patch('time.time', return_value=time.time() + 50):
            dna2 = "VOL00000000000"
            with open(self.input_file, 'w') as f:
                f.write(dna2 + "\n")

            run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # Heat should be (initial_heat - 0.5) + HEAT_PER_ITEM
        expected_heat = (initial_heat - 0.5) + HEAT_PER_ITEM
        self.assertAlmostEqual(state["system_heat"], expected_heat, places=3)

    def test_idempotency_no_heat_for_processed(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
        heat_after_first = state["system_heat"]

        # Run again with same DNA
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # Heat should be same (actually slightly less due to cooling between calls, but let's assume immediate)
        self.assertLessEqual(state["system_heat"], heat_after_first)

if __name__ == '__main__':
    unittest.main()
