import os
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch
from utils.dna_ui import main as run_batch, PersistenceError, DNAProcessingError

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

        # Mock Volume rule file with single subvar matching V100
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "amp": {"min": 0, "max": 1000, "pad": 4, "description": "Absolute amplitude"},
                    "lr": {"min": 0, "max": 100, "pad": 3, "description": "Left-channel dominance"},
                    "sur": {"min": 0, "max": 10, "pad": 2, "description": "Surround depth"},
                    "head": {"min": 0, "max": 60, "pad": 2, "description": "Headroom"}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_happy_path_execution(self):
        """Proof: Happy path parses valid DNA, creates ledger entries, and writes atomic outputs."""
        # VOL + amp(4) + lr(3) + sur(2) + head(2) = 14 chars total: VOL 0890 075 07 12
        valid_dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(valid_dna + "\n")

        run_batch()

        self.assertTrue(os.path.exists(self.json_output))
        self.assertTrue(os.path.exists(self.csv_output))
        self.assertTrue(os.path.exists(self.ledger_file))

        with open(self.json_output, 'r') as f:
            json_data = json.load(f)
        self.assertEqual(len(json_data), 1)
        self.assertEqual(json_data[0]['dna'], valid_dna)

        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)
        self.assertIn(valid_dna, ledger_data)
        self.assertEqual(ledger_data[valid_dna]['terminal_outcome'], 'success')

    def test_double_invocation_idempotency(self):
        """Proof: Double invocation with same DNA sequence is idempotent and does not duplicate output."""
        valid_dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(valid_dna + "\n")

        # First run
        run_batch()

        # Second run with same input
        with open(self.input_file, 'w') as f:
            f.write(valid_dna + "\n")

        run_batch()

        with open(self.json_output, 'r') as f:
            json_data = json.load(f)
        self.assertEqual(len(json_data), 1, "Duplicate side effect detected on double invocation")

    def test_persistence_failure_adversarial(self):
        """Adversarial Proof: Persistence crash guarantees atomic rollback (no output created)."""
        valid_dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(valid_dna + "\n")

        with patch('os.replace', side_effect=OSError("Disk write error")):
            with self.assertRaises(PersistenceError):
                run_batch()

        self.assertFalse(os.path.exists(self.json_output))
        self.assertFalse(os.path.exists(self.csv_output))

if __name__ == '__main__':
    unittest.main()
