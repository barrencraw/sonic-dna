import os
import json
import unittest
import tempfile
import shutil
from utils.dna_ui import run_batch, DNAStatus, LedgerLoadError


class TestChainContract(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.raw_dir = os.path.join(self.test_dir, 'data', 'raw')
        self.output_dir = os.path.join(self.test_dir, 'data', 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')
        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')

        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_happy_path(self):
        """Contract proof: Happy path processing produces expected output structures."""
        with open(self.input_file, 'w') as f:
            f.write("VOL12300000000\n")

        res = run_batch(project_root=self.test_dir)
        self.assertEqual(res["status"], DNAStatus.SUCCESS.value)
        self.assertEqual(res["processed"], 1)

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertTrue(os.path.exists(json_out))

    def test_idempotency_on_double_invocation(self):
        """Contract proof: Re-running batch on identical DNA sequence skips processing."""
        with open(self.input_file, 'w') as f:
            f.write("VOL12300000000\n")

        res1 = run_batch(project_root=self.test_dir)
        self.assertEqual(res1["processed"], 1)

        res2 = run_batch(project_root=self.test_dir)
        self.assertEqual(res2["processed"], 0)
        self.assertEqual(res2["skipped"], 1)

    def test_corrupted_ledger_raises_ledger_load_error(self):
        """Contract proof: Corrupted ledger triggers LedgerLoadError."""
        ledger_file = os.path.join(self.test_dir, 'data', 'processed_ledger.json')
        with open(ledger_file, 'w') as f:
            f.write("{invalid json content")

        with open(self.input_file, 'w') as f:
            f.write("VOL12300000000\n")

        with self.assertRaises(LedgerLoadError):
            run_batch(project_root=self.test_dir)


if __name__ == '__main__':
    unittest.main()
