import os
import json
import shutil
import unittest
import time
from unittest.mock import patch
from utils.dna_ui import main as run_batch, MAX_HEAT, BASE_HEAT_GAIN, VOL_HEAT_PENALTY

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        # Setup paths
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        # Backup existing data
        self.backup_folder = os.path.join(self.project_root, 'data_backup_thermal')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        # Ensure clean state
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Initialize empty state
        with open(self.ledger_path, 'w') as f:
            json.dump({
                "system_heat": 0.0,
                "last_processed_timestamp": time.time(),
                "ledger": {}
            }, f)

    def tearDown(self):
        # Restore backup
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation(self):
        # Process 3 DNA strings (not VOL)
        dnas = ["CLA00000000000", "CLA00000000001", "CLA00000000002"] # Need unique for idempotency
        # Note: We need a real prefix that exists in rules folder.
        # rules_Clarity.json has prefix 'CLA'? Let me check.
        # Actually I saw 'VOL' for Volume.

        # Using VOL for testing heat gain
        dnas = ["VOL00000000000", "VOL00000000001", "VOL00000000002"]
        # VOL cost = 0.1 + 0.2 = 0.3

        with open(self.input_file, 'w') as f:
            for d in dnas:
                f.write(d + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # Expected heat: 3 * 0.3 = 0.9
        self.assertAlmostEqual(state["system_heat"], 0.9)

    def test_cooling_over_time(self):
        # 1. Set high heat manually
        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
        state["system_heat"] = 5.0
        # Set timestamp to 20 minutes ago (1200 seconds)
        state["last_processed_timestamp"] = time.time() - 1200
        with open(self.ledger_path, 'w') as f:
            json.dump(state, f)

        # 2. Run batch (can be empty)
        # Note: we need to make sure run_batch doesn't just return if no DNA
        # Looking at dna_ui.py, it returns if not dna_list.
        # So we add one DNA string that is already in ledger
        dna = "VOL00000000000"
        state["ledger"][dna] = {"terminal_outcome": "success"}
        with open(self.ledger_path, 'w') as f:
            json.dump(state, f)

        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            new_state = json.load(f)

        # COOLING_RATE = 0.0083
        # Dissipated = 1200 * 0.0083 = 9.96
        # Heat should be max(0, 5.0 - 9.96) = 0.0
        self.assertEqual(new_state["system_heat"], 0.0)

    def test_thermal_overload_refusal(self):
        # 1. Set heat near limit
        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
        state["system_heat"] = 9.8
        state["last_processed_timestamp"] = time.time()
        with open(self.ledger_path, 'w') as f:
            json.dump(state, f)

        # 2. Try to process a VOL sequence (cost 0.3)
        # 9.8 + 0.3 = 10.1 > 10.0 (MAX_HEAT)
        dna = "VOL00000000003"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            new_state = json.load(f)

        # Heat should still be 9.8 (or slightly less due to cooling during run_batch,
        # but time difference will be negligible)
        self.assertLessEqual(new_state["system_heat"], 9.8)
        self.assertNotIn(dna, new_state["ledger"])

if __name__ == '__main__':
    unittest.main()
