import os
import json
import shutil
import unittest
import tempfile
from unittest.mock import patch

from utils.dna_ui import run_batch, DNAStatus, PersistenceError, AtomicWriteError, ThermalOverloadError

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

        # Mock rule file for Volume
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
        self.ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_happy_path_processing(self):
        with open(self.input_file, 'w') as f:
            f.write("VOL100\n")

        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        csv_out = os.path.join(self.output_dir, 'toSequence_parsed.csv')

        self.assertTrue(os.path.exists(json_out))
        self.assertTrue(os.path.exists(csv_out))

        with open(json_out, 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]['dna'], 'VOL100')
            self.assertEqual(data[0]['dna_sequence'], 'VOL100')

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)

        ledger = ledger_data.get('ledger', ledger_data)
        self.assertIn('VOL100', ledger)
        self.assertEqual(ledger['VOL100']['terminal_outcome'], DNAStatus.SUCCESS.value)

    def test_idempotency_double_invocation(self):
        with open(self.input_file, 'w') as f:
            f.write("VOL100\n")

        run_batch()
        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1, "Should not duplicate entries on double invocation")

    def test_persistence_failure_atomic(self):
        with open(self.input_file, 'w') as f:
            f.write("VOL100\n")

        with patch('os.replace', side_effect=OSError("Disk write error")):
            with self.assertRaises(PersistenceError):
                run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertFalse(os.path.exists(json_out))

if __name__ == '__main__':
    unittest.main()
