import os
import json
import shutil
import unittest
import time
from utils.dna_ui import main as run_batch, ThermalOverloadError, MAX_HEAT

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        # Setup paths
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        # Backup existing data if any
        self.backup_folder = os.path.join(self.project_root, 'data_backup')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
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
        # Base heat gain is 0.1, VOL penalty is 0.2 -> total 0.3 per VOL sequence
        dna1 = "VOL00000000000"
        dna2 = "VOL11111111111"

        with open(self.input_file, 'w') as f:
            f.write(f"{dna1}\n{dna2}\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        self.assertAlmostEqual(state['system_heat'], 0.6, places=2)
        self.assertIn(dna1, state['ledger'])
        self.assertIn(dna2, state['ledger'])

    def test_thermal_refusal(self):
        # MAX_HEAT is 10.0. 0.3 per sequence means 34 sequences will exceed 10.0
        dnas = [f"VOL{str(i).zfill(11)}" for i in range(40)]

        with open(self.input_file, 'w') as f:
            for dna in dnas:
                f.write(dna + "\n")

        # The current main() prints the error and stops, but doesn't re-raise to caller
        # unless we want to change it. Currently it catches ThermalOverloadError.
        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # It should have processed floor(10.0 / 0.3) = 33 sequences
        self.assertTrue(state['system_heat'] <= MAX_HEAT)
        self.assertEqual(len(state['ledger']), 33)

    def test_idempotency_no_heat(self):
        dna = "VOL00000000000"

        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            state1 = json.load(f)
        heat1 = state1['system_heat']

        # Run again with same DNA
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            state2 = json.load(f)
        heat2 = state2['system_heat']

        self.assertAlmostEqual(heat1, heat2, places=4)

    def test_cooling(self):
        dna = "VOL00000000000"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            state1 = json.load(f)
        heat1 = state1['system_heat']

        # Manually set the timestamp back in the past
        # COOLING_RATE = 0.0083 units/sec. To cool down 0.1 units, we need ~12 seconds.
        state1['last_processed_timestamp'] -= 100
        with open(self.ledger_path, 'w') as f:
            json.dump(state1, f)

        # Run batch again (can be empty or with new DNA)
        with open(self.input_file, 'w') as f:
            f.write("VOL11111111111\n") # New DNA to trigger another gain of 0.3

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state2 = json.load(f)

        expected_cooling = 100 * 0.0083 # 0.83
        expected_heat = max(0.0, heat1 - expected_cooling) + 0.3
        self.assertAlmostEqual(state2['system_heat'], expected_heat, places=2)

if __name__ == '__main__':
    unittest.main()
