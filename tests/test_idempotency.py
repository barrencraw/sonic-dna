import os
import json
import shutil
import unittest
import time
from utils.dna_ui import main as run_batch

class TestIdempotency(unittest.TestCase):
    def setUp(self):
        # Setup paths
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')
        self.csv_output = os.path.join(self.output_folder, 'toSequence_parsed.csv')

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
            shutil.move(self.backup_folder, self.data_folder)

    def test_double_invocation_same_key_preserves_cumulative_results(self):
        # 1. First invocation
        dna1 = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna1 + "\n")

        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['dna'], dna1)

        # 2. Second invocation with a DIFFERENT DNA
        dna2 = "VOL00000000000"
        with open(self.input_file, 'w') as f:
            f.write(dna2 + "\n")

        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 2, "Should have 2 entries (cumulative)")
        dnas = [entry['dna'] for entry in data]
        self.assertIn(dna1, dnas)
        self.assertIn(dna2, dnas)

        # 3. Third invocation with SAME DNA as first (idempotency hit)
        with open(self.input_file, 'w') as f:
            f.write(dna1 + "\n")

        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 2, "Should still have 2 entries after idempotency hit")

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
        dnas = [entry['dna'] for entry in data]
        self.assertIn(dna1, dnas)
        self.assertIn(dna2, dnas)

    def test_retry_after_transient_failure(self):
        dna = "VOL08900750712"

        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch() # Success

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertIn(dna, ledger)

        # If output file is lost, but ledger remains, it stays lost because of idempotency
        # but consistency is maintained (we don't duplicate).
        os.remove(self.json_output)

        new_dna = "VOL00000000000"
        with open(self.input_file, 'w') as f:
            f.write(new_dna + "\n")

        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        # Since VOL08900750712 was in the ledger, it was NOT re-processed.
        # Only VOL00000000000 is in the new output.
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['dna'], new_dna)

if __name__ == '__main__':
    unittest.main()
