import os
import json
import shutil
import unittest
import time
import datetime
from utils.dna_ui import main as run_batch, ThermalOverloadError, MAX_HEAT, HEAT_PER_SEQ, COOLING_RATE

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        # Setup paths
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

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

    def test_heat_accumulation(self):
        # VOL08900750712 is valid DNA for Volume
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        self.assertEqual(state['system_heat'], HEAT_PER_SEQ)
        self.assertIsNotNone(state['last_processed_timestamp'])

    def test_thermal_lockout(self):
        # We need enough DNA sequences to exceed MAX_HEAT
        # MAX_HEAT = 100, HEAT_PER_SEQ = 20. 6 sequences should trigger it.
        dnas = [f"VOL0890075071{i}" for i in range(6)]
        with open(self.input_file, 'w') as f:
            for dna in dnas:
                f.write(dna + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # Check ledger
        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # Should have processed 5 successfully before locking out
        self.assertEqual(state['system_heat'], 100.0)
        self.assertEqual(len(state['ledger']), 5)

        # Output file should have 5 entries
        with open(self.json_output, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_heat_dissipation(self):
        # Manually set high heat in ledger
        state = {
            "system_heat": 100.0,
            "last_processed_timestamp": (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=10)).strftime('%Y-%m-%dT%H:%M:%SZ'),
            "ledger": {}
        }
        with open(self.ledger_path, 'w') as f:
            json.dump(state, f)

        # Run with one DNA
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            new_state = json.load(f)

        # Dissipation = 10s * 2.0 = 20.0
        # New heat = 100.0 - 20.0 + 20.0 (for the new seq) = 100.0
        # Let's verify it didn't lockout (it shouldn't because 80 < 100 at start of loop)
        self.assertAlmostEqual(new_state['system_heat'], 100.0, delta=1.0)
        self.assertIn(dna, new_state['ledger'])

    def test_idempotency_no_heat(self):
        dna = "VOL08900750712"
        # Pre-populate ledger
        state = {
            "system_heat": 50.0,
            "last_processed_timestamp": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            "ledger": {
                dna: {"terminal_outcome": "success", "timestamp": "..."}
            }
        }
        with open(self.ledger_path, 'w') as f:
            json.dump(state, f)

        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            new_state = json.load(f)

        # Heat should NOT have increased because it was skipped
        # It might have decreased slightly due to dissipation if a few ms passed,
        # but certainly shouldn't be 70.0
        self.assertLessEqual(new_state['system_heat'], 50.0)

if __name__ == '__main__':
    unittest.main()
