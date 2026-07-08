import os
import json
import shutil
import unittest
import time
import datetime
from utils.dna_ui import main as run_batch, ThermalOverloadError, MAX_HEAT, HEAT_PER_SEQ

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        # Backup existing data
        self.backup_folder = os.path.join(self.project_root, 'data_fatigue_backup')
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
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        self.assertEqual(state["system_heat"], HEAT_PER_SEQ)
        self.assertIn("last_processed_timestamp", state)

    def test_heat_dissipation(self):
        # 1. Process one to establish heat
        dna1 = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna1 + "\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
        initial_heat = state["system_heat"]

        # 2. Artificially set back the timestamp in the ledger
        state["last_processed_timestamp"] = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=10)).strftime('%Y-%m-%dT%H:%M:%SZ')
        with open(self.ledger_path, 'w') as f:
            json.dump(state, f)

        # 3. Run again with a new DNA
        dna2 = "VOL00000000000"
        with open(self.input_file, 'w') as f:
            f.write(dna2 + "\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # Expected heat: (initial_heat - (10s * COOLING_RATE)) + HEAT_PER_SEQ
        # COOLING_RATE is 2.0
        expected_heat = (initial_heat - 20.0) + HEAT_PER_SEQ
        if expected_heat < HEAT_PER_SEQ: expected_heat = HEAT_PER_SEQ # min heat after processing 1 is HEAT_PER_SEQ if it fully cooled before

        # We use assertAlmostEqual because of small timing differences
        self.assertAlmostEqual(state["system_heat"], expected_heat, delta=1.0)

    def test_thermal_lockout(self):
        # Generate enough DNA to exceed MAX_HEAT
        # MAX_HEAT = 100, HEAT_PER_SEQ = 20 -> 5 sequences should reach 100
        # The 6th should be refused.
        dnas = [f"VOL{i:011d}" for i in range(10)]
        with open(self.input_file, 'w') as f:
            for d in dnas:
                f.write(d + "\n")

        # The 6th sequence should trigger ThermalOverloadError
        with self.assertRaises(ThermalOverloadError):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        self.assertGreaterEqual(state["system_heat"], MAX_HEAT)
        # Check that some items were processed but not all
        # 5 should be success, some might be refused but not in ledger yet because loop breaks
        # Actually in my implementation, I break BEFORE processing the one that would exceed MAX_HEAT?
        # NO, I check if heat >= MAX_HEAT.
        # 1st: heat=0, OK, then heat=20
        # 2nd: heat=20, OK, then heat=40
        # 3rd: heat=40, OK, then heat=60
        # 4th: heat=60, OK, then heat=80
        # 5th: heat=80, OK, then heat=100
        # 6th: heat=100, REFUSED

        processed_count = len(state["ledger"])
        self.assertEqual(processed_count, 5)

if __name__ == '__main__':
    unittest.main()
