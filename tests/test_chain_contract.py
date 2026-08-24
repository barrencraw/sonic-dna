import os
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch

from utils.dna_ui import run_batch, PersistenceError, AtomicWriteError, DNAStatus

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

        # Mock a Volume rule
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "amp": {"min": 0, "max": 1000, "pad": 4, "description": "amp"},
                    "lr": {"min": 0, "max": 100, "pad": 3, "description": "lr"},
                    "sur": {"min": 0, "max": 10, "pad": 2, "description": "sur"},
                    "head": {"min": 0, "max": 60, "pad": 2, "description": "head"}
                }
            }, f)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.csv_output = os.path.join(self.output_dir, 'toSequence_parsed.csv')

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_happy_path_batch_parsing(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch(correlation_id="test-happy-path", actor_id="test_actor")

        self.assertTrue(os.path.exists(self.json_output))
        self.assertTrue(os.path.exists(self.csv_output))

        with open(self.json_output, 'r') as f:
            json_data = json.load(f)
        self.assertEqual(len(json_data), 1)
        self.assertEqual(json_data[0]['dna'], dna)
        self.assertEqual(json_data[0]['dna_sequence'], dna)

        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)
        ledger = ledger_data.get('ledger', ledger_data)
        self.assertIn(dna, ledger)
        self.assertEqual(ledger[dna]['terminal_outcome'], 'success')

    def test_double_invocation_idempotency(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch(correlation_id="test-idempotency-1")

        with open(self.json_output, 'r') as f:
            json_data1 = json.load(f)
        self.assertEqual(len(json_data1), 1)

        # Second invocation
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch(correlation_id="test-idempotency-2")

        with open(self.json_output, 'r') as f:
            json_data2 = json.load(f)
        self.assertEqual(len(json_data2), 1, "Should not duplicate entries on second run")

    def test_persistence_failure_rollback(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        with patch('os.replace', side_effect=OSError("Disk write error")):
            with self.assertRaises(PersistenceError):
                run_batch(correlation_id="test-failure")

        self.assertFalse(os.path.exists(self.json_output))
        self.assertFalse(os.path.exists(self.csv_output))

if __name__ == '__main__':
    unittest.main()
