import sys
from unittest.mock import MagicMock

# Mock GUI and audio modules if not installed
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

import unittest
import os
import json
import shutil
import tempfile
from unittest.mock import patch
from utils.dna_ui import run_batch, PersistenceError, load_ledger

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

        # Mock Volume rule JSON
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w', encoding='utf-8') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "amp": {"min": 0, "max": 1000, "pad": 4, "description": "amp"},
                    "lr": {"min": 0, "max": 100, "pad": 3, "description": "lr"},
                    "sur": {"min": 0, "max": 10, "pad": 2, "description": "sur"},
                    "head": {"min": 0, "max": 60, "pad": 2, "description": "head"}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_happy_path_batch_parsing(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch(correlation_id="test-happy-path")

        # Verify output JSON exists and has entry
        self.assertTrue(os.path.exists(self.json_output))
        with open(self.json_output, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['dna'], dna)

        # Verify ledger
        self.assertTrue(os.path.exists(self.ledger_path))
        ledger = load_ledger(self.ledger_path)
        self.assertIn(dna, ledger)
        self.assertEqual(ledger[dna]['terminal_outcome'], 'success')

    def test_adversarial_double_invocation_idempotency(self):
        dna = "VOL08900750712"

        # 1. First run
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch(correlation_id="run-1")

        with open(self.json_output, 'r', encoding='utf-8') as f:
            data_1 = json.load(f)
        self.assertEqual(len(data_1), 1)

        # 2. Second run with same DNA
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch(correlation_id="run-2")

        with open(self.json_output, 'r', encoding='utf-8') as f:
            data_2 = json.load(f)
        self.assertEqual(len(data_2), 1, "Duplicate DNA must not produce duplicate entries in output")

    def test_persistence_failure_atomicity(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        # Simulate I/O error during output writing
        with patch('os.replace', side_effect=OSError("Disk write error")):
            with self.assertRaises(PersistenceError):
                run_batch(correlation_id="run-fail")

        # Verify outputs were not created/overwritten in corrupt state
        self.assertFalse(os.path.exists(self.json_output))

if __name__ == '__main__':
    unittest.main()
