import os
import json
import shutil
import unittest
import datetime
from unittest.mock import patch, MagicMock
from utils.dna_ui import main as run_batch, ThermalOverloadError, load_ledger, save_ledger

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        # Backup existing data folder if present
        self.backup_folder = os.path.join(self.project_root, 'data_backup_fatigue')
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

    def test_heat_accumulation_and_idempotency(self):
        """Verify that heat accumulates on new sequences but NOT on duplicate/idempotent sequences."""
        dna1 = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna1 + "\n")

        run_batch()

        ledger, system_state = load_ledger(self.ledger_path)
        self.assertEqual(system_state['core_heat'], 2.0)

        # Second invocation with same DNA sequence should hit dedupe and NOT add heat
        with open(self.input_file, 'w') as f:
            f.write(dna1 + "\n")

        run_batch()

        ledger, system_state = load_ledger(self.ledger_path)
        self.assertAlmostEqual(system_state['core_heat'], 2.0, delta=0.5)

    def test_thermal_lockout_refusal_and_ui_message_keys(self):
        """Verify that exceeding 10.0 heat units triggers ThermalOverloadError with UI message keys."""
        # Write 6 unique DNA sequences (each adds 2.0 heat units -> 6 * 2.0 = 12.0 > 10.0 threshold)
        dna_sequences = [f"VOL089007507{i:02d}" for i in range(6)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dna_sequences) + "\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        err = cm.exception
        self.assertEqual(err.consequence, "Heat Accumulation")
        self.assertEqual(err.reason, "Thermal Lockout")
        self.assertEqual(err.next_action_hint, "Wait for dissipation. The system is indifferent to your deadlines.")

        # Check that system heat is recorded and preserved up to the refusal threshold (10.0)
        ledger, system_state = load_ledger(self.ledger_path)
        self.assertEqual(system_state['core_heat'], 10.0)
        # 5 sequences processed (5 * 2.0 = 10.0), 6th sequence refused
        self.assertEqual(len(ledger), 5)

    def test_cooling_decay_over_time(self):
        """Verify that simulated elapsed time cools down core heat at 0.5 heat units per second."""
        # Preset core heat to 8.0 at a timestamp 10 seconds in the past
        past_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=10)
        system_state = {
            'core_heat': 8.0,
            'last_processed_timestamp': past_time.strftime('%Y-%m-%dT%H:%M:%SZ')
        }
        save_ledger(self.ledger_path, {}, system_state)

        # Process 1 new sequence (+2.0 heat) after 10s cooling (-5.0 heat -> 8.0 - 5.0 + 2.0 = 5.0 heat)
        new_dna = "VOL08900750799"
        with open(self.input_file, 'w') as f:
            f.write(new_dna + "\n")

        run_batch()

        ledger, new_system_state = load_ledger(self.ledger_path)
        self.assertAlmostEqual(new_system_state['core_heat'], 5.0, delta=0.5)

    def test_no_silent_drains_on_thermal_lockout(self):
        """Verify that when thermal overload occurs in main.py watcher, toSequence.txt is NOT cleared."""
        import main

        # Preset heat to 10.0 (lockout state)
        now_time = datetime.datetime.now(datetime.timezone.utc)
        system_state = {
            'core_heat': 10.0,
            'last_processed_timestamp': now_time.strftime('%Y-%m-%dT%H:%M:%SZ')
        }
        save_ledger(self.ledger_path, {}, system_state)

        unprocessed_dna = "VOL08900750788"
        with open(self.input_file, 'w') as f:
            f.write(unprocessed_dna + "\n")

        # Calling main.process_once() should encounter ThermalOverloadError and exit with code 1
        with self.assertRaises(SystemExit) as cm:
            main.process_once()

        self.assertEqual(cm.exception.code, 1)

        # Crucial check: input file MUST retain unprocessed DNA sequence (no silent drain)
        with open(self.input_file, 'r') as f:
            content = f.read().strip()
        self.assertEqual(content, unprocessed_dna)

if __name__ == '__main__':
    unittest.main()
