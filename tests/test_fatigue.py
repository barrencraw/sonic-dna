import os
import json
import shutil
import unittest
import time
import datetime
from utils.dna_ui import main as run_batch, ThermalOverloadError

class TestThermalFatigue(unittest.TestCase):
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

        # Initialize empty ledger state
        with open(self.ledger_path, 'w') as f:
            json.dump({'system_heat': 0.0, 'last_processed_timestamp': None, 'ledger': {}}, f)

    def tearDown(self):
        # Restore backup
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation(self):
        # 5 sequences should reach 100 heat (5 * 20)
        dna_lines = ["VOL00100100101", "VOL00100100102", "VOL00100100103", "VOL00100100104", "VOL00100100105"]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dna_lines) + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        self.assertAlmostEqual(state['system_heat'], 100.0)
        self.assertEqual(len(state['ledger']), 5)

    def test_thermal_lockout(self):
        # 6 sequences should trigger lockout on the 6th
        dna_lines = [f"VOL0010010010{i}" for i in range(6)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dna_lines) + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # Should have processed exactly 5 before lockout
        self.assertEqual(len(state['ledger']), 5)
        self.assertAlmostEqual(state['system_heat'], 100.0)

    def test_heat_dissipation(self):
        # Process 1 sequence to get 20 heat
        with open(self.input_file, 'w') as f:
            f.write("VOL00100100101\n")
        run_batch()

        # Manually set timestamp back in time (10 seconds ago)
        # 10s * 2.0/s = 20 heat dissipated
        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        last_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=10)
        state['last_processed_timestamp'] = last_time.strftime('%Y-%m-%dT%H:%M:%SZ')
        with open(self.ledger_path, 'w') as f:
            json.dump(state, f)

        # Run again with new sequence
        with open(self.input_file, 'w') as f:
            f.write("VOL00100100102\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # Should be: 20 (old) - 20 (dissipated) + 20 (new) = 20
        self.assertAlmostEqual(state['system_heat'], 20.0, delta=1.0)
        self.assertEqual(len(state['ledger']), 2)

    def test_persistence_lockout_across_runs(self):
        # 5 sequences to reach max heat
        dna_lines = [f"VOL0010010010{i}" for i in range(5)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dna_lines) + "\n")
        run_batch()

        # Next run should immediately lockout
        with open(self.input_file, 'w') as f:
            f.write("VOL00100100199\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

if __name__ == '__main__':
    unittest.main()
