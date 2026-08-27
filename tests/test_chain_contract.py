import os
import sys
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch

from utils.dna_ui import (
    run_batch,
    DNAStatus,
    PersistenceError,
    AtomicWriteError,
    InputReadError
)


class TestChainContract(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        self.raw_dir = os.path.join(self.test_dir, 'data', 'raw')
        self.output_dir = os.path.join(self.test_dir, 'data', 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')
        self.ledger_path = os.path.join(self.test_dir, 'data', 'processed_ledger.json')

        os.makedirs(self.raw_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.rules_dir, exist_ok=True)

        # Mock Volume rule
        rule_content = {
            "variable": "Volume",
            "prefix": "VOL",
            "subvars": {
                "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
            }
        }
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w', encoding='utf-8') as f:
            json.dump(rule_content, f)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_happy_path_processing(self):
        dna = "VOL123"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(f"{dna}\n")

        run_batch(correlation_id="test_happy", actor_id="test_runner")

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        csv_out = os.path.join(self.output_dir, 'toSequence_parsed.csv')

        self.assertTrue(os.path.exists(json_out))
        self.assertTrue(os.path.exists(csv_out))

        with open(json_out, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]['dna_sequence'], dna)

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)
            ledger = ledger_data.get('ledger', ledger_data)
            self.assertIn(dna, ledger)
            self.assertEqual(ledger[dna]['terminal_outcome'], DNAStatus.SUCCESS.value)

    def test_idempotency_double_invocation(self):
        dna = "VOL123"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(f"{dna}\n")

        # First run
        run_batch(correlation_id="test_idemp_1", actor_id="test_runner")

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r', encoding='utf-8') as f:
            data_first = json.load(f)
        self.assertEqual(len(data_first), 1)

        # Second run with same DNA sequence
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(f"{dna}\n")

        run_batch(correlation_id="test_idemp_2", actor_id="test_runner")

        with open(json_out, 'r', encoding='utf-8') as f:
            data_second = json.load(f)
        self.assertEqual(len(data_second), 1, "Duplicate DNA sequence must not be re-appended to output")

    def test_persistence_failure_recovery(self):
        dna = "VOL456"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(f"{dna}\n")

        with patch('os.replace', side_effect=OSError("Disk write error")):
            with self.assertRaises(AtomicWriteError):
                run_batch(correlation_id="test_failure", actor_id="test_runner")

        # Verify input file remains intact for retry
        with open(self.input_file, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            self.assertEqual(content, dna)


if __name__ == '__main__':
    unittest.main()
