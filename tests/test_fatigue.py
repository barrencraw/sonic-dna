import os
import json
import shutil
import unittest
import datetime
import tempfile
from utils.dna_ui import run_batch, ThermalOverloadError, load_ledger, save_ledger

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        # Backup existing data if any
        self.backup_folder = os.path.join(self.project_root, 'data_backup')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        # Ensure clean state for test
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Initialize empty ledger
        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)

    def tearDown(self):
        # Restore backup
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            if os.path.exists(self.backup_folder):
                shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation(self):
        # 1. Process 1 DNA sequence
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        # Check ledger and heat
        state = load_ledger(self.ledger_path)
        self.assertEqual(state["system_heat"], 20.0)

        # 2. Process another DNA sequence
        dna2 = "VOL00000000000"
        with open(self.input_file, 'w') as f:
            f.write(dna2 + "\n")

        run_batch()

        state = load_ledger(self.ledger_path)
        # 20.0 + 20.0 = 40.0. Since some cooling may have occurred, we use non-strict bounds.
        self.assertGreater(state["system_heat"], 35.0)
        self.assertLessEqual(state["system_heat"], 40.0)

    def test_heat_dissipation(self):
        # 1. Set heat to 50.0 and last_update to 10 seconds ago
        state = {
            "system_heat": 50.0,
            "last_update": (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=10)).strftime('%Y-%m-%dT%H:%M:%SZ'),
            "ledger": {}
        }
        save_ledger(self.ledger_path, state)

        # 2. Run batch with a sequence to process
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        # Heat should dissipate by ~10 seconds * 2.0/sec = 20.0 units.
        # So heat goes from 50.0 -> 30.0. Then we process 1 sequence: 30.0 + 20.0 = 50.0.
        # Account for a small amount of extra elapsed time.
        state = load_ledger(self.ledger_path)
        self.assertGreater(state["system_heat"], 45.0)
        self.assertLessEqual(state["system_heat"], 50.0)

    def test_lockout_and_refusal(self):
        # 1. Set heat to 110.0 (sufficiently above MAX_HEAT to survive minor cooling)
        state = {
            "system_heat": 110.0,
            "last_update": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            "ledger": {}
        }
        save_ledger(self.ledger_path, state)

        # 2. Try to process a new sequence. It should raise ThermalOverloadError.
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        with self.assertRaises(ThermalOverloadError) as context:
            run_batch()

        self.assertIn("Thermal Lockout", str(context.exception))
        self.assertIn("The system is indifferent to your deadlines.", str(context.exception))

    def test_partial_processing_before_lockout(self):
        # 1. Set heat to 85.0 (so processing one item adds 20.0 -> 105.0, triggering lockout for the second)
        state = {
            "system_heat": 85.0,
            "last_update": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            "ledger": {}
        }
        save_ledger(self.ledger_path, state)

        # 2. Process two new DNA sequences.
        # The first should succeed (raising heat to 105.0).
        # The second should trigger a lockout error (raising ThermalOverloadError).
        dna1 = "VOL08900750712"
        dna2 = "VOL00000000000"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna1}\n{dna2}\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # Check that the first dna succeeded and was committed, but the second was not processed
        state = load_ledger(self.ledger_path)
        ledger = state.get("ledger", state)
        self.assertIn(dna1, ledger)
        self.assertEqual(ledger[dna1]["terminal_outcome"], "success")
        self.assertNotIn(dna2, ledger)
        self.assertGreaterEqual(state["system_heat"], 100.0)

if __name__ == '__main__':
    unittest.main()
