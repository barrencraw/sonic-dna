import os
import json
import shutil
import tempfile
import unittest
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

        # Valid Volume rule definition
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
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')
        self.json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.csv_out = os.path.join(self.output_dir, 'toSequence_parsed.csv')

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_happy_path_processing(self):
        with open(self.input_file, 'w') as f:
            f.write("VOL123\n")

        run_batch(correlation_id="test-corr-happy")

        self.assertTrue(os.path.exists(self.json_out))
        self.assertTrue(os.path.exists(self.csv_out))
        self.assertTrue(os.path.exists(self.ledger_file))

        with open(self.json_out, 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]['dna'], 'VOL123')
            self.assertEqual(data[0]['rule'], 'Volume')

        with open(self.ledger_file, 'r') as f:
            ledger = json.load(f)
            self.assertIn('VOL123', ledger)
            self.assertEqual(ledger['VOL123']['terminal_outcome'], 'success')

    def test_adversarial_double_invocation(self):
        with open(self.input_file, 'w') as f:
            f.write("VOL123\n")

        # First run
        run_batch(correlation_id="test-corr-1")

        # Second run with same input
        run_batch(correlation_id="test-corr-2")

        with open(self.json_out, 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1, "Must remain idempotent with exactly 1 entry")

    def test_adversarial_persistence_failure(self):
        with open(self.input_file, 'w') as f:
            f.write("VOL123\n")

        with patch('os.replace', side_effect=OSError("Atomic replacement failure")):
            with self.assertRaises(PersistenceError):
                run_batch(correlation_id="test-corr-fail")

        # Atomic contract: no outputs left on disk when failure occurs
        self.assertFalse(os.path.exists(self.json_out))
        self.assertFalse(os.path.exists(self.csv_out))
        self.assertFalse(os.path.exists(self.ledger_file))

if __name__ == '__main__':
    unittest.main()
