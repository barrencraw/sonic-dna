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
        rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(rule_file, 'w', encoding='utf-8') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_happy_path_and_telemetry(self):
        dna_seq = "VOL100"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna_seq + "\n")

        with patch('builtins.print') as mock_print:
            run_batch(correlation_id="test-corr-123", actor_id="test_actor")

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertTrue(os.path.exists(json_out))

        with open(json_out, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]['dna'], dna_seq)
            self.assertEqual(data[0]['dna_sequence'], dna_seq)
            self.assertEqual(data[0]['rule'], 'Volume')

        with open(self.ledger_file, 'r', encoding='utf-8') as f:
            ledger = json.load(f)
            self.assertIn(dna_seq, ledger)
            self.assertEqual(ledger[dna_seq]['terminal_outcome'], DNAStatus.SUCCESS.value)

    def test_double_invocation_deduplication(self):
        dna_seq = "VOL200"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna_seq + "\n")

        run_batch(correlation_id="corr-1")

        # Rewrite input file with same sequence
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna_seq + "\n")

        run_batch(correlation_id="corr-2")

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1, "Duplicate DNA sequence must not add a second entry to outputs")

    def test_atomic_failure_recovery(self):
        dna_seq = "VOL300"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna_seq + "\n")

        with patch('os.replace', side_effect=OSError("Disk write error")):
            with self.assertRaises(AtomicWriteError):
                run_batch(correlation_id="corr-fail")

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertFalse(os.path.exists(json_out), "Partial files must not be committed on atomic write failure")

if __name__ == '__main__':
    unittest.main()
