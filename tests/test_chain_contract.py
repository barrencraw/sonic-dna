import sys
from unittest.mock import MagicMock

# Mock GUI dependencies before any imports
sys.modules.setdefault("PySide6", MagicMock())
sys.modules.setdefault("PySide6.QtWidgets", MagicMock())
sys.modules.setdefault("PySide6.QtCore", MagicMock())
sys.modules.setdefault("PySide6.QtGui", MagicMock())
sys.modules.setdefault("torch", MagicMock())
sys.modules.setdefault("torchaudio", MagicMock())
sys.modules.setdefault("sounddevice", MagicMock())

import unittest
import os
import shutil
import tempfile
import json
from unittest.mock import patch
from utils.dna_ui import run_batch, PersistenceError

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
        self.json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.csv_out = os.path.join(self.output_dir, 'toSequence_parsed.csv')

        # Create dummy rule file
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "v1": {"description": "volume subvar 1", "min": 0, "max": 999, "pad": 3},
                    "v2": {"description": "volume subvar 2", "min": 0, "max": 999, "pad": 3},
                    "v3": {"description": "volume subvar 3", "min": 0, "max": 999, "pad": 3},
                    "v4": {"description": "volume subvar 4", "min": 0, "max": 99, "pad": 2}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_happy_path(self):
        """Happy path: valid sequence is parsed and output/ledger files are generated."""
        dna_seq = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna_seq}\n")

        run_batch(correlation_id="test-happy-path")

        self.assertTrue(os.path.exists(self.json_out))
        self.assertTrue(os.path.exists(self.csv_out))
        self.assertTrue(os.path.exists(self.ledger_file))

        with open(self.json_out, 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]['dna'], dna_seq)

        with open(self.ledger_file, 'r') as f:
            ledger = json.load(f)
            self.assertIn(dna_seq, ledger)
            self.assertEqual(ledger[dna_seq]['terminal_outcome'], 'success')

    def test_double_invocation_idempotency(self):
        """Adversarial: Invoking the batch runner twice with the same DNA sequence does not duplicate entries."""
        dna_seq = "VOL08900750712"

        # 1st run
        with open(self.input_file, 'w') as f:
            f.write(f"{dna_seq}\n")

        run_batch(correlation_id="run-1")

        with open(self.json_out, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

        # 2nd run with same input
        with open(self.input_file, 'w') as f:
            f.write(f"{dna_seq}\n")

        run_batch(correlation_id="run-2")

        with open(self.json_out, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1, "Duplicate DNA string should not produce duplicate output entries")

    def test_persistence_failure_atomicity(self):
        """Adversarial: Failure during atomic rename prevents creation of corrupt output files."""
        dna_seq = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna_seq}\n")

        with patch('os.replace', side_effect=OSError("Atomic Rename Failed")):
            with self.assertRaises(PersistenceError):
                run_batch(correlation_id="fail-run")

        self.assertFalse(os.path.exists(self.json_out))
        self.assertFalse(os.path.exists(self.csv_out))
        self.assertFalse(os.path.exists(self.ledger_file))

if __name__ == '__main__':
    unittest.main()
