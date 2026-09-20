import os
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch
from utils.dna_ui import main as run_batch, PersistenceError, RuleLoadError


class TestChainContract(unittest.TestCase):
    def setUp(self):
        self.old_cwd = os.getcwd()
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)

        # Copy actual rules from repo root
        real_rules = os.path.join(self.old_cwd, 'rules')
        shutil.copytree(real_rules, self.rules_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.csv_output = os.path.join(self.output_dir, 'toSequence_parsed.csv')

        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_happy_path_processing(self):
        """Verify happy path processing and correct file creation."""
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        self.assertTrue(os.path.exists(self.json_output))
        self.assertTrue(os.path.exists(self.csv_output))
        self.assertTrue(os.path.exists(self.ledger_file))

        with open(self.ledger_file, 'r') as f:
            ledger = json.load(f)
        self.assertIn(dna, ledger)
        self.assertEqual(ledger[dna]['terminal_outcome'], 'success')

    def test_idempotency_double_invocation(self):
        """Verify that running batch twice with same DNA does not add duplicates."""
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # First run
        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

        # Second run with same input
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        # Check output still has 1 item
        with open(self.json_output, 'r') as f:
            data_after = json.load(f)
        self.assertEqual(len(data_after), 1)

    def test_persistence_failure_preserves_input_and_prevents_partial_write(self):
        """Verify that infrastructure I/O errors raise PersistenceError and do not mutate outputs."""
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        with patch('os.replace', side_effect=OSError("Disk write error")):
            with self.assertRaises(PersistenceError):
                run_batch()

        # Output files must not exist or be mutated
        self.assertFalse(os.path.exists(self.json_output))
        self.assertFalse(os.path.exists(self.csv_output))

        # Input file remains intact for retry
        with open(self.input_file, 'r') as f:
            self.assertEqual(f.read().strip(), dna)


if __name__ == '__main__':
    unittest.main()
