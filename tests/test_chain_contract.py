import os
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch
from utils.dna_ui import run_batch, AtomicWriteError, PersistenceError

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
        self.json_output = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.csv_output = os.path.join(self.output_dir, 'toSequence_parsed.csv')

        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("VOL08900750712\n")

        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w', encoding='utf-8') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3},
                    "pan": {"description": "panning", "min": 0, "max": 999, "pad": 3},
                    "mute": {"description": "mute flag", "min": 0, "max": 9, "pad": 1},
                    "solo": {"description": "solo flag", "min": 0, "max": 9, "pad": 1},
                    "phase": {"description": "phase angle", "min": 0, "max": 360, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_happy_path_parsing(self):
        run_batch()

        self.assertTrue(os.path.exists(self.json_output))
        self.assertTrue(os.path.exists(self.csv_output))

        with open(self.json_output, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]['dna'], 'VOL08900750712')
            self.assertEqual(data[0]['dna_sequence'], 'VOL08900750712')

        with open(self.ledger_file, 'r', encoding='utf-8') as f:
            ledger = json.load(f)
            self.assertIn('VOL08900750712', ledger)
            self.assertEqual(ledger['VOL08900750712']['terminal_outcome'], 'success')

    def test_double_invocation_idempotency(self):
        run_batch()

        # Call again with same sequence
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("VOL08900750712\n")

        run_batch()

        with open(self.json_output, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1, "Idempotency failed: sequence processed twice")

    def test_persistence_failure_raises_typed_error(self):
        with patch('os.replace', side_effect=OSError("Disk write error")):
            with self.assertRaises((AtomicWriteError, PersistenceError)):
                run_batch()

if __name__ == '__main__':
    unittest.main()
