import os
import json
import shutil
import unittest
import time
from unittest.mock import patch
from utils.dna_ui import main as run_batch, DNAStatus, ThermalOverloadError

class TestFatigue(unittest.TestCase):
    def setUp(self):
        # Setup paths
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        # Backup existing data
        self.backup_folder = os.path.join(self.project_root, 'data_backup_fatigue')
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
        # Each processed sequence should add 5.0 heat
        # Create unique valid DNAs
        dna_list = [f"VOL{i:04}0750712" for i in range(3)]
        with open(self.input_file, 'w') as f:
            for dna in dna_list:
                f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        self.assertEqual(state["system_heat"], 15.0)
        self.assertEqual(len(state["ledger"]), 3)

    def test_heat_dissipation(self):
        # Manually set high heat in ledger
        initial_heat = 50.0
        # Set timestamp to 20 seconds ago
        past_time = time.time() - 20.0
        state = {
            "system_heat": initial_heat,
            "last_processed_timestamp": past_time,
            "ledger": {}
        }
        with open(self.ledger_path, 'w') as f:
            json.dump(state, f)

        # Process one item
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        # Dissipation: 50.0 - (20.0 * 0.5) = 40.0
        # Accumulation: 40.0 + 5.0 = 45.0
        with open(self.ledger_path, 'r') as f:
            new_state = json.load(f)

        # Using delta for float comparison and timing jitter
        self.assertAlmostEqual(new_state["system_heat"], 45.0, delta=1.0)

    def test_thermal_lockout(self):
        # Set heat just below threshold
        state = {
            "system_heat": 99.0,
            "last_processed_timestamp": time.time(),
            "ledger": {}
        }
        with open(self.ledger_path, 'w') as f:
            json.dump(state, f)

        # Try to process 2 items. First should pass (heat -> 104.0), second should be REFUSED.
        dna1 = "VOL00010750712"
        dna2 = "VOL00020750712"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna1}\n{dna2}\n")

        # run_batch should raise ThermalOverloadError because dna2 is refused
        with self.assertRaises(ThermalOverloadError):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            final_state = json.load(f)

        self.assertEqual(final_state["ledger"][dna1]["terminal_outcome"], DNAStatus.SUCCESS.value)
        self.assertEqual(final_state["ledger"][dna2]["terminal_outcome"], DNAStatus.REFUSED.value)
        self.assertGreater(final_state["system_heat"], 100.0)

    def test_refused_items_retry(self):
        # Items marked REFUSED should be retried in next run if heat dissipated
        dna = "VOL00030750712"

        # 1. Force refusal
        state = {
            "system_heat": 110.0,
            "last_processed_timestamp": time.time(),
            "ledger": {}
        }
        with open(self.ledger_path, 'w') as f:
            json.dump(state, f)

        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # We need to ensure that the ledger is SAVED even if ThermalOverloadError is raised.
        # CURRENT IMPLEMENTATION: if new_processed_count > 0 it saves.
        # But if ONLY refused items, new_processed_count is 0.
        # AH! I see. REFUSED items don't count towards new_processed_count.
        # I should probably update main() to save even if only REFUSED items.

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            state1 = json.load(f)

        # This will still fail until I fix utils/dna_ui.py
        self.assertIn(dna, state1["ledger"])
        self.assertEqual(state1["ledger"][dna]["terminal_outcome"], DNAStatus.REFUSED.value)

if __name__ == '__main__':
    unittest.main()
