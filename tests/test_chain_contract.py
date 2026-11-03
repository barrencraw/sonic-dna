import os
import json
import csv
import shutil
import tempfile
import unittest
from unittest.mock import patch

from utils.dna_ui import run_batch, PersistenceError

class TestChainContract(unittest.TestCase):
    """
    Contract proof tests for the DNA Batch Parsing chain verifying:
    1. Happy path batch processing and ledger updates.
    2. Double invocation idempotency (no duplicate entries, zero new writes).
    3. Adversarial failure (persistence failure rolls back atomic writes).
    """

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.csv_output = os.path.join(self.output_dir, 'toSequence_parsed.csv')

        # Create valid test rule
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_happy_path_processing(self):
        """Happy path: processes valid DNA sequence and commits ledger and outputs."""
        dna = "VOL100"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna}\n")

        correlation_id = "test-corr-1234"
        run_batch(correlation_id=correlation_id)

        # Output JSON and CSV created
        self.assertTrue(os.path.exists(self.json_output))
        self.assertTrue(os.path.exists(self.csv_output))
        self.assertTrue(os.path.exists(self.ledger_file))

        with open(self.json_output, 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]['dna'], dna)

        with open(self.ledger_file, 'r') as f:
            ledger = json.load(f)
            self.assertIn(dna, ledger)
            self.assertEqual(ledger[dna]['terminal_outcome'], 'success')
            self.assertEqual(ledger[dna]['correlation_id'], correlation_id)

    def test_idempotency_double_invocation(self):
        """Idempotency: double invocation does not duplicate output rows or re-touch outputs."""
        dna = "VOL100"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna}\n")

        run_batch(correlation_id="corr-first")

        # Record modification times
        json_mtime_before = os.path.getmtime(self.json_output)
        csv_mtime_before = os.path.getmtime(self.csv_output)

        # Second invocation with same DNA sequence
        with open(self.input_file, 'w') as f:
            f.write(f"{dna}\n")

        run_batch(correlation_id="corr-second")

        with open(self.json_output, 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1, "Duplicate record found in output JSON")

        with open(self.csv_output, 'r') as f:
            reader = list(csv.DictReader(f))
            self.assertEqual(len(reader), 1, "Duplicate record found in output CSV")

        # Because new_processed_count == 0, output files should not have been overwritten
        self.assertEqual(os.path.getmtime(self.json_output), json_mtime_before)
        self.assertEqual(os.path.getmtime(self.csv_output), csv_mtime_before)

    def test_adversarial_persistence_failure(self):
        """Adversarial test: failure during atomic rename raises PersistenceError without leaving half-baked files."""
        dna = "VOL200"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna}\n")

        with patch('os.replace', side_effect=OSError("Atomic rename failed")):
            with self.assertRaises(PersistenceError):
                run_batch(correlation_id="corr-fail")

        # Outputs and ledger should NOT exist
        self.assertFalse(os.path.exists(self.json_output))
        self.assertFalse(os.path.exists(self.csv_output))
        self.assertFalse(os.path.exists(self.ledger_file))

if __name__ == '__main__':
    unittest.main()
