import os
import sys
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch

from utils.dna_ui import run_batch, PersistenceError, DNAProcessingError

class TestChainContract(unittest.TestCase):
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

        # Mock a Volume rule file matching structure VOL08900750712
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "amp": {"description": "amp", "min": 0, "max": 1000, "pad": 4},
                    "lr": {"description": "lr", "min": 0, "max": 100, "pad": 3},
                    "sur": {"description": "sur", "min": 0, "max": 10, "pad": 2},
                    "head": {"description": "head", "min": 0, "max": 60, "pad": 2}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_happy_path(self):
        """Proof: Happy path parses input sequence, creates output files and ledger entry."""
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch(correlation_id="test-happy-path")

        self.assertTrue(os.path.exists(self.json_output))
        self.assertTrue(os.path.exists(self.csv_output))
        self.assertTrue(os.path.exists(self.ledger_file))

        with open(self.ledger_file, 'r') as f:
            ledger = json.load(f)
        self.assertIn(dna, ledger)
        self.assertEqual(ledger[dna]['terminal_outcome'], 'success')

    def test_double_invocation_idempotency(self):
        """Proof: Double invocation with identical DNA sequence does not produce duplicate entries."""
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch(correlation_id="test-run-1")

        with open(self.json_output, 'r') as f:
            parsed1 = json.load(f)
        self.assertEqual(len(parsed1), 1)

        # Second invocation
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch(correlation_id="test-run-2")

        with open(self.json_output, 'r') as f:
            parsed2 = json.load(f)
        self.assertEqual(len(parsed2), 1, "Output must remain idempotent upon re-invocation")

    def test_persistence_failure_rollback(self):
        """Proof: Adversarial infrastructure failure during persistence raises PersistenceError and leaves output clean."""
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        with patch('os.replace', side_effect=OSError("Disk write error")):
            with self.assertRaises(PersistenceError):
                run_batch(correlation_id="test-infra-fail")

        self.assertFalse(os.path.exists(self.json_output), "JSON output should not exist after failure")
        self.assertFalse(os.path.exists(self.csv_output), "CSV output should not exist after failure")

if __name__ == '__main__':
    unittest.main()
