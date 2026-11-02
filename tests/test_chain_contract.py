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

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.csv_out = os.path.join(self.output_dir, 'toSequence_parsed.csv')
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')

        # Create sample rule for Volume (prefix VOL)
        rule_vol = {
            "variable": "Volume",
            "prefix": "VOL",
            "subvars": {
                "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
            }
        }
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump(rule_vol, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_happy_path_processing(self):
        """Verify that valid DNA sequences are parsed, outputs created, and ledger updated."""
        dna = "VOL123"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch(correlation_id="test_contract_happy", actor_id="test_runner")

        self.assertTrue(os.path.exists(self.json_out))
        self.assertTrue(os.path.exists(self.csv_out))
        self.assertTrue(os.path.exists(self.ledger_file))

        with open(self.json_out, 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]['dna'], dna)
            self.assertEqual(data[0]['rule'], 'Volume')

        with open(self.ledger_file, 'r') as f:
            ledger = json.load(f)
            self.assertIn(dna, ledger)
            self.assertEqual(ledger[dna]['terminal_outcome'], 'success')

    def test_double_invocation_idempotency(self):
        """Adversarial check: invoking batch twice with identical DNA must not duplicate entries."""
        dna = "VOL123"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        # Second run with same input
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.json_out, 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1, "Expected exactly 1 record after duplicate invocation")

    def test_persistence_failure_atomicity(self):
        """Adversarial check: failure during atomic rename rolls back and does not create partial outputs."""
        dna = "VOL123"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        with patch('os.replace', side_effect=OSError("Disk write error")):
            with self.assertRaises(PersistenceError):
                run_batch()

        self.assertFalse(os.path.exists(self.json_out))
        self.assertFalse(os.path.exists(self.csv_out))
        self.assertFalse(os.path.exists(self.ledger_file))

if __name__ == '__main__':
    unittest.main()
