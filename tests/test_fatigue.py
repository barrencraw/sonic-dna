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

        # Backup existing data if any
        self.backup_folder = os.path.join(self.project_root, 'data_backup_fatigue')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        # Ensure clean state for test
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
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # 1 sequence = 5.0 heat. Dissipation might occur but should be minimal in this fast test.
        self.assertGreaterEqual(state['system_heat'], 4.9)
        self.assertLessEqual(state['system_heat'], 5.0)

    def test_thermal_lockout(self):
        # We need 21 sequences to exceed 100.0 heat (21 * 5 = 105)
        dnas = [f"VOL{str(i).zfill(11)}" for i in range(25)]
        with open(self.input_file, 'w') as f:
            for dna in dnas:
                f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        ledger = state['ledger']
        outcomes = [entry['terminal_outcome'] for entry in ledger.values()]

        self.assertIn(DNAStatus.SUCCESS.value, outcomes)
        self.assertIn(DNAStatus.REFUSED.value, outcomes)

        # Verify refusal reason and hint
        refused_entries = [e for e in ledger.values() if e['terminal_outcome'] == DNAStatus.REFUSED.value]
        for entry in refused_entries:
            self.assertEqual(entry['reason'], "Thermal Lockout")
            self.assertEqual(entry['hint'], "Dissipation required. System indifferent to urgency.")

    def test_heat_dissipation(self):
        # 1. Set high heat
        with open(self.ledger_path, 'w') as f:
            json.dump({
                "system_heat": 10.0,
                "last_processed_timestamp": time.time() - 10, # 10 seconds ago
                "ledger": {}
            }, f)

        # 2. Run empty batch to trigger dissipation
        # No, wait, main() returns if no DNA found.
        # Let's add one DNA string.
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # 10s * 0.5/s = 5.0 units dissipated.
        # Initial 10.0 - 5.0 + 5.0 (from new processing) = 10.0
        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        self.assertAlmostEqual(state['system_heat'], 10.0, delta=0.1)

    def test_idempotency_refused_retry(self):
        # 1. Set state to just below threshold
        with open(self.ledger_path, 'w') as f:
            json.dump({
                "system_heat": 98.0,
                "last_processed_timestamp": time.time(),
                "ledger": {}
            }, f)

        dna1 = "VOL00000000001"
        dna2 = "VOL00000000002"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna1}\n{dna2}\n")

        run_batch() # dna1 success (98+5=103), dna2 refused

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['ledger'][dna1]['terminal_outcome'], DNAStatus.SUCCESS.value)
        self.assertEqual(state['ledger'][dna2]['terminal_outcome'], DNAStatus.REFUSED.value)

        # 2. Reset heat manually and retry
        state['system_heat'] = 0.0
        state['last_processed_timestamp'] = time.time()
        with open(self.ledger_path, 'w') as f:
            json.dump(state, f)

        with open(self.input_file, 'w') as f:
            f.write(f"{dna1}\n{dna2}\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
        # dna1 should still be success (skipped processing)
        # dna2 should now be success (retried because it was REFUSED)
        self.assertEqual(state['ledger'][dna1]['terminal_outcome'], DNAStatus.SUCCESS.value)
        self.assertEqual(state['ledger'][dna2]['terminal_outcome'], DNAStatus.SUCCESS.value)

if __name__ == '__main__':
    unittest.main()
