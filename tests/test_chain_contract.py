import os
import json
import csv
import shutil
import tempfile
import unittest
from unittest.mock import patch
from utils.dna_ui import main as run_batch, PersistenceError

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

        # Mock a rule file for Volume ('VOL')
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

    def test_contract_happy_path(self):
        """Verify happy path parsing and output persistence."""
        dna = "VOL100"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        csv_out = os.path.join(self.output_dir, 'toSequence_parsed.csv')
        ledger_out = os.path.join(self.data_dir, 'processed_ledger.json')

        self.assertTrue(os.path.exists(json_out))
        self.assertTrue(os.path.exists(csv_out))
        self.assertTrue(os.path.exists(ledger_out))

        with open(ledger_out, 'r', encoding='utf-8') as f:
            ledger = json.load(f)
            self.assertIn(dna, ledger)
            self.assertEqual(ledger[dna]['terminal_outcome'], 'success')

    def test_contract_idempotency_double_invoke(self):
        """Verify double invocation skips already processed key and produces no duplicate entries."""
        dna = "VOL100"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r', encoding='utf-8') as f:
            first_data = json.load(f)

        self.assertEqual(len(first_data), 1)

        # Double invoke
        run_batch()

        with open(json_out, 'r', encoding='utf-8') as f:
            second_data = json.load(f)

        self.assertEqual(len(second_data), 1, "Output file must not duplicate processed keys")

    def test_contract_atomic_persistence_failure(self):
        """Verify atomic rollback when disk/write failure occurs during atomic persistence."""
        dna = "VOL100"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        with patch('os.replace', side_effect=OSError("Disk write error")):
            with self.assertRaises(PersistenceError):
                run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        csv_out = os.path.join(self.output_dir, 'toSequence_parsed.csv')

        self.assertFalse(os.path.exists(json_out))
        self.assertFalse(os.path.exists(csv_out))

if __name__ == '__main__':
    unittest.main()
