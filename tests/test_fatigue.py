import os
import json
import shutil
import unittest
import time
from utils.dna_ui import main as run_batch, DNAStatus

class TestFatigue(unittest.TestCase):
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

        # Initialize empty ledger
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
        # 1 DNA sequence should add 5.0 heat
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # We allow for a tiny bit of dissipation during execution,
        # but it should be very close to 5.0
        self.assertGreaterEqual(state['system_heat'], 4.9)
        self.assertLessEqual(state['system_heat'], 5.0)

    def test_thermal_lockout(self):
        # Set heat close to threshold
        with open(self.ledger_path, 'w') as f:
            json.dump({
                "system_heat": 101.0,
                "last_processed_timestamp": time.time(),
                "ledger": {}
            }, f)

        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        self.assertEqual(state['ledger'][dna]['terminal_outcome'], DNAStatus.REFUSED.value)
        # Heat should NOT have increased
        self.assertLessEqual(state['system_heat'], 101.0)

    def test_dissipation(self):
        # Set high heat but old timestamp
        old_time = time.time() - 100 # 100 seconds ago
        with open(self.ledger_path, 'w') as f:
            json.dump({
                "system_heat": 50.0,
                "last_processed_timestamp": old_time,
                "ledger": {}
            }, f)

        # 100 seconds * 0.5 units/sec = 50.0 units dissipated.
        # Heat should drop to 0.0 before processing new DNA.

        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # Heat should be exactly 5.0 (50 dissipated to 0, then +5 for the new DNA)
        self.assertAlmostEqual(state['system_heat'], 5.0, delta=0.1)

if __name__ == '__main__':
    unittest.main()
