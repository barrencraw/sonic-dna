import os
import json
import shutil
import unittest
from utils.dna_ui import main as run_batch

class TestPartialSuccess(unittest.TestCase):
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
        self.backup_folder = os.path.join(self.project_root, 'data_backup_partial')
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

    def test_mixed_success_and_failure(self):
        # VOL + amp(4) + lr(3) + sur(2) + head(2) = 14 chars
        valid_dna = "VOL08900750712"
        invalid_dna = "INVALID123" # Prefix not recognized

        with open(self.input_file, 'w') as f:
            f.write(f"{valid_dna}\n{invalid_dna}\n")

        run_batch()

        # Verify ledger
        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)

        self.assertIn(valid_dna, ledger)
        self.assertEqual(ledger[valid_dna]['terminal_outcome'], 'success')

        self.assertIn(invalid_dna, ledger)
        self.assertTrue(ledger[invalid_dna]['terminal_outcome'].startswith('error:'))

        # Verify JSON output
        with open(self.json_output, 'r') as f:
            data = json.load(f)

        self.assertEqual(len(data), 2)

        # Check valid entry
        valid_entry = next(e for e in data if e['dna'] == valid_dna)
        self.assertEqual(valid_entry['rule'], 'Volume')
        self.assertIn('parsed', valid_entry)

        # Check error entry
        error_entry = next(e for e in data if e['dna'] == invalid_dna)
        self.assertIn('error', error_entry)

    def test_atomic_persistence_on_partial_failure(self):
        # Verify that even with partial failures (parse errors), the successful ones are still committed
        valid_dna = "VOL08900750712"
        invalid_dna = "FOO999"

        with open(self.input_file, 'w') as f:
            f.write(f"{valid_dna}\n{invalid_dna}\n")

        run_batch()

        # Both should be in ledger
        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertIn(valid_dna, ledger)
        self.assertIn(invalid_dna, ledger)

        # Re-run with another valid DNA. The previous ones should be skipped.
        new_valid_dna = "VOL00000000000"
        with open(self.input_file, 'w') as f:
            f.write(f"{valid_dna}\n{invalid_dna}\n{new_valid_dna}\n")

        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        # Total entries should be 3
        self.assertEqual(len(data), 3)
        dnas = [e['dna'] for e in data]
        self.assertIn(valid_dna, dnas)
        self.assertIn(invalid_dna, dnas)
        self.assertIn(new_valid_dna, dnas)

if __name__ == '__main__':
    unittest.main()
