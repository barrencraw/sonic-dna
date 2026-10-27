import sys
from unittest.mock import MagicMock

# Mock GUI and heavy hardware dependencies
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

import os
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch
from utils.dna_ui import (
    run_batch,
    PersistenceError,
    AtomicWriteError,
    RuleLoadError,
    DNAProcessingError
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
        os.makedirs(self.rules_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')
        self.json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.csv_out = os.path.join(self.output_dir, 'toSequence_parsed.csv')

        # Mock Volume rule definition matching VOL08900750712 structure
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "amp": {"min": 0, "max": 1000, "pad": 4, "description": "Amplitude"},
                    "lr": {"min": 0, "max": 100, "pad": 3, "description": "Left-Right balance"},
                    "sur": {"min": 0, "max": 10, "pad": 2, "description": "Surround"},
                    "head": {"min": 0, "max": 60, "pad": 2, "description": "Headroom"}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_happy_path_parsing_and_contract(self):
        """Happy path: valid sequence is parsed, outputs written atomically, ledger updated."""
        dna_seq = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna_seq}\n")

        run_batch(correlation_id="test-cid-1")

        # Verify JSON & CSV outputs exist
        self.assertTrue(os.path.exists(self.json_out))
        self.assertTrue(os.path.exists(self.csv_out))

        with open(self.json_out, 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]['dna'], dna_seq)

        # Verify ledger updated
        with open(self.ledger_file, 'r') as f:
            ledger = json.load(f)
            self.assertIn(dna_seq, ledger)
            self.assertEqual(ledger[dna_seq]['terminal_outcome'], 'success')

    def test_double_invocation_idempotency(self):
        """Adversarial test: Double invocation of the same key does not create duplicate entries."""
        dna_seq = "VOL08900750712"

        with open(self.input_file, 'w') as f:
            f.write(f"{dna_seq}\n")

        run_batch(correlation_id="test-cid-first")

        # Second invocation with same DNA sequence
        with open(self.input_file, 'w') as f:
            f.write(f"{dna_seq}\n")

        run_batch(correlation_id="test-cid-second")

        with open(self.json_out, 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1, "Should deduplicate and contain exactly 1 entry")

    def test_persistence_failure_recovery(self):
        """Adversarial test: Infrastructure failure during output write raises typed AtomicWriteError without corrupting output."""
        dna_seq = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna_seq}\n")

        with patch('os.replace', side_effect=OSError("Disk write error")):
            with self.assertRaises(AtomicWriteError):
                run_batch(correlation_id="test-cid-fail")

        # Verify output files do not exist (not left torn/corrupt)
        self.assertFalse(os.path.exists(self.json_out))
        self.assertFalse(os.path.exists(self.csv_out))

if __name__ == '__main__':
    unittest.main()
