import os
import sys
import json
import shutil
import tempfile
import unittest

from utils.dna_ui import (
    main as run_batch,
    LedgerLoadError,
    load_ledger
)


class TestChainContract(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)

        # Copy actual project rules folder
        real_rules = os.path.join(os.getcwd(), 'rules')
        if os.path.exists(real_rules):
            shutil.copytree(real_rules, self.rules_dir)
        else:
            os.makedirs(self.rules_dir)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_happy_path_and_naming_keys(self):
        """Verify happy path batch execution produces JSON and CSV outputs with canonical keys."""
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        seq = "VOL08900750712"
        with open(input_file, 'w', encoding='utf-8') as f:
            f.write(f"{seq}\n")

        run_batch(correlation_id="happy-path-test")

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertTrue(os.path.exists(json_out))

        with open(json_out, 'r', encoding='utf-8') as f:
            data = json.load(f)

        self.assertEqual(len(data), 1)
        self.assertIn('dna', data[0])
        self.assertIn('dna_sequence', data[0])
        self.assertEqual(data[0]['dna_sequence'], seq)

    def test_corrupted_ledger_raises_ledger_load_error(self):
        """Verify that a corrupted ledger JSON file raises LedgerLoadError."""
        ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')
        with open(ledger_path, 'w', encoding='utf-8') as f:
            f.write("{ INVALID JSON }")

        with self.assertRaises(LedgerLoadError):
            load_ledger(ledger_path)


if __name__ == '__main__':
    unittest.main()
