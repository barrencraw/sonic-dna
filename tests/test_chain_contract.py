import unittest
import os
import shutil
import tempfile
import json
from unittest.mock import patch
from utils.dna_ui import run_batch, PersistenceError

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

        # Create valid volume rule
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
        """Happy path: raw DNA sequence processed, ledger updated, JSON and CSV emitted."""
        dna = "VOL100"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna}\n")

        run_batch()

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

    def test_adversarial_double_invocation(self):
        """Adversarial double invocation: second run skips sequence, outputs stay idempotent."""
        dna = "VOL100"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna}\n")

        run_batch()

        # Second invocation
        with open(self.input_file, 'w') as f:
            f.write(f"{dna}\n")

        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1, "Duplicate DNA sequence must not be re-appended to JSON")

    def test_persistence_failure_atomicity(self):
        """Infra failure: failure during atomic replace leaves no half-written or corrupted outputs."""
        dna = "VOL100"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna}\n")

        with patch('os.replace', side_effect=OSError("Disk write error")):
            with self.assertRaises(PersistenceError):
                run_batch()

        self.assertFalse(os.path.exists(self.json_output))
        self.assertFalse(os.path.exists(self.csv_output))
        self.assertFalse(os.path.exists(self.ledger_file))

if __name__ == '__main__':
    unittest.main()
