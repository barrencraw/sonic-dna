import os
import json
import csv
import shutil
import tempfile
import unittest
from unittest.mock import patch

from utils.dna_ui import run_batch, AtomicWriteError, DNAStatus

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

        # Create rule file matching real Volume rule layout
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 99999999999, "pad": 11}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_happy_path_and_canonical_keys(self):
        dna_seq = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna_seq}\n")

        run_batch(correlation_id="happy-path-cid", actor_id="test_runner")

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        csv_out = os.path.join(self.output_dir, 'toSequence_parsed.csv')

        self.assertTrue(os.path.exists(json_out))
        self.assertTrue(os.path.exists(csv_out))

        with open(json_out, 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]['dna'], dna_seq)
            self.assertEqual(data[0]['dna_sequence'], dna_seq)

        with open(csv_out, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['dna'], dna_seq)
            self.assertEqual(rows[0]['dna_sequence'], dna_seq)

        with open(self.ledger_file, 'r') as f:
            ledger = json.load(f)
            self.assertIn(dna_seq, ledger)
            self.assertEqual(ledger[dna_seq]['terminal_outcome'], DNAStatus.SUCCESS.value)

    def test_idempotency_double_invocation(self):
        dna_seq = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna_seq}\n")

        run_batch(correlation_id="cid-1", actor_id="test_runner")

        # Second invocation
        with open(self.input_file, 'w') as f:
            f.write(f"{dna_seq}\n")

        run_batch(correlation_id="cid-2", actor_id="test_runner")

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)

    def test_atomic_write_failure_preserves_state(self):
        dna_seq = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna_seq}\n")

        with patch('os.replace', side_effect=OSError("Atomic replace failed")):
            with self.assertRaises(AtomicWriteError):
                run_batch(correlation_id="cid-fail", actor_id="test_runner")

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertFalse(os.path.exists(json_out))

if __name__ == '__main__':
    unittest.main()
