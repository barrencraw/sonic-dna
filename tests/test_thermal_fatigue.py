import os
import json
import shutil
import unittest
import time
from utils.dna_ui import main as run_batch, ThermalOverloadError

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        # Setup paths
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
        # Restore backup
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation_and_refusal(self):
        # HEAT_PER_ITEM = 1.0, MAX_HEAT = 10.0
        # Prepare 11 unique DNA strings
        dna_strings = [f"VOL{str(i).zfill(11)}" for i in range(11)]

        with open(self.input_file, 'w') as f:
            for dna in dna_strings:
                f.write(dna + "\n")

        # First run should process 10 and then raise ThermalOverloadError
        with self.assertRaises(ThermalOverloadError):
            run_batch(base_dir=self.project_root)

        # Verify ledger state
        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        self.assertEqual(state["system_heat"], 10.0)
        self.assertEqual(len(state["ledger"]), 10)

        # 11th one should not be in ledger
        self.assertNotIn(dna_strings[10], state["ledger"])

    def test_cooling(self):
        # Process 5 items -> 5.0 heat
        dna_strings = [f"VOL{str(i).zfill(11)}" for i in range(5)]
        with open(self.input_file, 'w') as f:
            for dna in dna_strings:
                f.write(dna + "\n")

        run_batch(base_dir=self.project_root)

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state["system_heat"], 5.0)

        # Simulate time passage (e.g., 2 minutes = 120 seconds)
        # COOLING_RATE = 0.0083
        # Expected cooling = 120 * 0.0083 = 0.996

        state["last_processed_timestamp"] -= 120
        with open(self.ledger_path, 'w') as f:
            json.dump(state, f)

        # Run batch again (with same or no new items) to trigger cooling
        with open(self.input_file, 'w') as f:
            f.write(dna_strings[0] + "\n") # Dedupe hit, but triggers main() logic

        run_batch(base_dir=self.project_root)

        with open(self.ledger_path, 'r') as f:
            new_state = json.load(f)

        self.assertLess(new_state["system_heat"], 5.0)
        self.assertAlmostEqual(new_state["system_heat"], 5.0 - (120 * 0.0083), delta=0.05)

    def test_idempotency_with_heat(self):
        # Process same item twice
        dna = "VOL00000000001"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch(base_dir=self.project_root)
        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state["system_heat"], 1.0)

        # Second run with same item
        run_batch(base_dir=self.project_root)
        with open(self.ledger_path, 'r') as f:
            state2 = json.load(f)

        # Heat should NOT increase for dedupe hit (it might decrease slightly due to cooling)
        self.assertLessEqual(state2["system_heat"], 1.0)
        self.assertGreater(state2["system_heat"], 0.9)

if __name__ == '__main__':
    unittest.main()
