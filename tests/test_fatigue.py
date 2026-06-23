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
        # Restore backup
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation_and_lockout(self):
        # Create enough DNA strings to exceed MAX_HEAT
        num_items = int(MAX_HEAT) + 1
        dnas = [f"VOL{i:011d}" for i in range(num_items)]

        with open(self.input_file, 'w') as f:
            for dna in dnas:
                f.write(dna + "\n")

        # First run should raise ThermalOverloadError
        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # Check ledger for heat
        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        self.assertEqual(state["system_heat"], MAX_HEAT, "Heat should be capped at MAX_HEAT due to lockout")
        self.assertEqual(len(state["ledger"]), int(MAX_HEAT), f"Should have processed exactly {int(MAX_HEAT)} items before lockout")

    def test_cooling_and_idempotency(self):
        # 1. Fill up heat
        dna_new = "VOL99999999999"
        with open(self.input_file, 'w') as f:
            for i in range(int(MAX_HEAT)):
                f.write(f"VOL{i:011d}\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state["system_heat"], MAX_HEAT)

        # 2. Try to process one more (new one), should fail
        with open(self.input_file, 'w') as f:
            f.write(dna_new + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # 3. Wait for cooling (or mock time, but let's wait a bit and check if heat decreased)
        # Instead of waiting a long time, we can manually manipulate the ledger timestamp
        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # Set timestamp 100 seconds ago
        state["last_processed_timestamp"] = time.time() - 100
        with open(self.ledger_path, 'w') as f:
            json.dump(state, f)

        # COOLING_RATE_PER_SEC = 0.01, so 100s = 1.0 heat reduction
        run_batch() # Should now succeed for 1 item

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # Heat was 10.0, cooled by 1.0 to 9.0, then processed 1 item (+1.0) -> 10.0
        self.assertAlmostEqual(state["system_heat"], MAX_HEAT, places=1)
        self.assertIn(dna_new, state["ledger"])

    def test_no_silent_drains_on_lockout(self):
        """State must be persisted even when ThermalOverloadError is raised."""
        with open(self.input_file, 'w') as f:
            for i in range(int(MAX_HEAT) + 1):
                f.write(f"VOL{i:011d}\n")

        try:
            run_batch()
        except ThermalOverloadError:
            pass

        self.assertTrue(os.path.exists(self.ledger_path), "Ledger should be saved even on lockout")
        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
        self.assertGreater(state["system_heat"], 0)

if __name__ == '__main__':
    unittest.main()
