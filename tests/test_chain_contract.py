import os
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch
from utils.dna_ui import main as run_batch, PersistenceError, load_ledger

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

        # Mock a rule file for Volume ('VOL')
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_happy_path_processing(self):
        """Happy path: process valid sequence and verify output files and ledger updates."""
        dna = "VOL089"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        csv_out = os.path.join(self.output_dir, 'toSequence_parsed.csv')

        self.assertTrue(os.path.exists(json_out))
        self.assertTrue(os.path.exists(csv_out))

        ledger = load_ledger(self.ledger_path)
        self.assertIn(dna, ledger)
        self.assertEqual(ledger[dna]['terminal_outcome'], 'success')

    def test_adversarial_double_invocation(self):
        """Adversarial: re-run same key. Deduplication hit must prevent duplicate entries."""
        dna = "VOL089"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data_first = json.load(f)
        self.assertEqual(len(data_first), 1)

        # Double invoke with same DNA sequence
        run_batch()

        with open(json_out, 'r') as f:
            data_second = json.load(f)
        self.assertEqual(len(data_second), 1, "Duplicate key should not add extra entries to parsed JSON")

    def test_persistence_failure_retains_atomicity(self):
        """Infra failure during atomic output commit should raise PersistenceError and leave outputs untouched."""
        dna = "VOL089"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        with patch('os.replace', side_effect=OSError("Disk Full / Write Failure")):
            with self.assertRaises(PersistenceError):
                run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        csv_out = os.path.join(self.output_dir, 'toSequence_parsed.csv')

        self.assertFalse(os.path.exists(json_out))
        self.assertFalse(os.path.exists(csv_out))

if __name__ == '__main__':
    unittest.main()
