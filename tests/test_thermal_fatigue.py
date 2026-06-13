import os
import json
import shutil
import unittest
import time
from unittest.mock import patch
from utils.dna_ui import main as run_batch, load_state, MAX_HEAT, HEAT_PER_ITEM

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        # Backup existing data if any
        self.backup_folder = os.path.join(self.project_root, 'data_backup_thermal')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

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
        dna1 = "VOL08900750712"
        dna2 = "VOL00000000000"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna1}\n{dna2}\n")

        run_batch()

        state = load_state(self.ledger_path)
        # Expected heat: HEAT_PER_ITEM * 2
        self.assertAlmostEqual(state["system_heat"], HEAT_PER_ITEM * 2)

    def test_thermal_lockout(self):
        # Generate more DNA strings than MAX_HEAT / HEAT_PER_ITEM
        count = int(MAX_HEAT / HEAT_PER_ITEM) + 2
        dnas = [f"VOL{str(i).zfill(11)}" for i in range(count)]

        with open(self.input_file, 'w') as f:
            for dna in dnas:
                f.write(dna + "\n")

        run_batch()

        state = load_state(self.ledger_path)
        expected_processed = int(MAX_HEAT / HEAT_PER_ITEM)
        self.assertEqual(len(state["ledger"]), expected_processed)
        self.assertTrue(state["system_heat"] <= MAX_HEAT)

    def test_cooling_dissipation(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # 1. Process one item to increase heat
        run_batch()
        state1 = load_state(self.ledger_path)
        heat1 = state1["system_heat"]
        last_ts = state1["last_processed_timestamp"]
        self.assertAlmostEqual(heat1, HEAT_PER_ITEM)

        # 2. Mock time to simulate cooling
        with patch('time.time') as mocked_time:
            # We need to simulate that 'now' in apply_cooling is 100s after 'last_processed_timestamp'
            mocked_time.return_value = last_ts + 100.0

            # Re-read the file with the same DNA to trigger processing (it'll be skipped by idempotency)
            # but apply_cooling should run at the start of main()
            with open(self.input_file, 'w') as f:
                f.write(dna + "\n")

            run_batch()

        state2 = load_state(self.ledger_path)
        # Cooling rate is 0.01/sec. 100 seconds = 1.0 cooling.
        # heat1 was 1.0. 1.0 - 1.0 = 0.0.
        self.assertAlmostEqual(state2["system_heat"], 0.0)

if __name__ == '__main__':
    unittest.main()
