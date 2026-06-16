import os
import json
import shutil
import unittest
import time
from utils.dna_ui import main as run_batch, DNAStatus

class TestIdempotency(unittest.TestCase):
    def setUp(self):
        # Setup paths
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'ledger.json')
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

        # Initialize empty ledger in structured format
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

    def test_double_invocation_same_key(self):
        # DNA for Volume (prefix 'VOL')
        dna = "VOL08900750712"

        # 1. First invocation
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['dna_sequence'], dna)

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
        ledger = state.get('ledger', state) # Support both formats
        self.assertIn(dna, ledger)
        self.assertEqual(ledger[dna]['terminal_outcome'], DNAStatus.SUCCESS.value)

        # 2. Second invocation with same DNA
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        # Verify no duplicate entry in output
        with open(self.json_output, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1, "Should NOT have added a second entry for the same DNA")

    def test_mixed_duplicates(self):
        dna1 = "VOL08900750712"
        dna2 = "VOL00000000000"

        with open(self.input_file, 'w') as f:
            f.write(f"{dna1}\n{dna1}\n{dna2}\n")

        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)
        # It should process dna1 (once) and dna2 (once)
        self.assertEqual(len(data), 2, "Should have exactly 2 entries")
        dnas = [entry['dna_sequence'] for entry in data]
        self.assertIn(dna1, dnas)
        self.assertIn(dna2, dnas)

    def test_migration_from_legacy_ledger(self):
        dna = "VOL11111111111"
        # Migration logic expects processed_ledger.json in data/
        legacy_ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        os.makedirs(self.data_folder, exist_ok=True)
        with open(legacy_ledger_path, 'w') as f:
            json.dump({dna: {"terminal_outcome": "success", "timestamp": "2025-01-01 00:00:00"}}, f)

        if os.path.exists(self.ledger_path):
            os.remove(self.ledger_path)

        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        # Should skip because it was migrated
        # Actually, in migration, we load it into state but it might not be in the output files
        # because those are separate. But the ledger hit should prevent re-processing.
        if os.path.exists(self.json_output):
            with open(self.json_output, 'r') as f:
                data = json.load(f)
            self.assertEqual(len(data), 0)

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
        self.assertIn(dna, state['ledger'])

if __name__ == '__main__':
    unittest.main()
