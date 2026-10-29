import os
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch
from utils.dna_ui import run_batch, PersistenceError, get_ledger_map

class TestChainContract(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.rules_dir, exist_ok=True)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.csv_output = os.path.join(self.output_dir, 'toSequence_parsed.csv')

        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w', encoding='utf-8') as f:
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
        dna = "VOL100"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch(correlation_id="test-happy-path-001")

        self.assertTrue(os.path.exists(self.json_output))
        self.assertTrue(os.path.exists(self.csv_output))
        self.assertTrue(os.path.exists(self.ledger_path))

        with open(self.json_output, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
        self.assertEqual(len(json_data), 1)
        self.assertEqual(json_data[0]['dna'], dna)
        self.assertEqual(json_data[0]['dna_sequence'], dna)

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger = get_ledger_map(json.load(f))
        self.assertIn(dna, ledger)
        self.assertEqual(ledger[dna]['terminal_outcome'], 'success')

    def test_double_invocation_idempotency(self):
        dna = "VOL100"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        # First run
        run_batch(correlation_id="test-idempotency-run1")

        with open(self.json_output, 'r', encoding='utf-8') as f:
            first_run_data = json.load(f)
        self.assertEqual(len(first_run_data), 1)

        # Second run (double invocation)
        run_batch(correlation_id="test-idempotency-run2")

        with open(self.json_output, 'r', encoding='utf-8') as f:
            second_run_data = json.load(f)

        # Output should not duplicate entries
        self.assertEqual(len(second_run_data), 1)

    def test_persistence_failure_recovery(self):
        dna = "VOL200"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        with patch('json.dump', side_effect=IOError("Simulated write error")):
            with self.assertRaises(PersistenceError):
                run_batch(correlation_id="test-failure-001")

        self.assertFalse(os.path.exists(self.json_output))
        self.assertFalse(os.path.exists(self.csv_output))

if __name__ == '__main__':
    unittest.main()
