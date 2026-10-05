import sys
from unittest.mock import MagicMock, patch

# Mock PySide6 / GUI dependencies if not available
mock_pyside6 = MagicMock()
sys.modules.setdefault("PySide6", mock_pyside6)
sys.modules.setdefault("PySide6.QtWidgets", mock_pyside6)
sys.modules.setdefault("PySide6.QtCore", mock_pyside6)
sys.modules.setdefault("PySide6.QtGui", mock_pyside6)
sys.modules.setdefault("torch", MagicMock())
sys.modules.setdefault("torchaudio", MagicMock())
sys.modules.setdefault("sounddevice", MagicMock())
sys.modules.setdefault("numpy", MagicMock())
sys.modules.setdefault("scipy", MagicMock())
sys.modules.setdefault("requests", MagicMock())
sys.modules.setdefault("watchdog", MagicMock())

import unittest
import os
import shutil
import tempfile
import json
from utils.dna_ui import run_batch, PersistenceError, AtomicWriteError, DNAProcessingError


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

        # Volume rule matching 14-char DNA VOL08900750712
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w', encoding='utf-8') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "amp": {"min": 0, "max": 1000, "pad": 4, "description": "Absolute amplitude"},
                    "lr": {"min": 0, "max": 100, "pad": 3, "description": "Left-channel dominance"},
                    "sur": {"min": 0, "max": 10, "pad": 2, "description": "Surround depth"},
                    "head": {"min": 0, "max": 60, "pad": 2, "description": "Headroom"}
                }
            }, f)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_happy_path_processing(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(f"{dna}\n")

        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        csv_out = os.path.join(self.output_dir, 'toSequence_parsed.csv')

        self.assertTrue(os.path.exists(json_out))
        self.assertTrue(os.path.exists(csv_out))

        with open(json_out, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]['dna'], dna)

        with open(self.ledger_file, 'r', encoding='utf-8') as f:
            ledger = json.load(f)
            self.assertIn(dna, ledger)
            self.assertEqual(ledger[dna]['terminal_outcome'], 'success')

    def test_idempotency_double_invocation(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(f"{dna}\n")

        run_batch()

        # Second invocation
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(f"{dna}\n")

        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1, "Duplicate key should not add extra entries")

    def test_persistence_failure_rollback(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(f"{dna}\n")

        with patch('os.replace', side_effect=OSError("Disk write error")):
            with self.assertRaises(PersistenceError):
                run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        csv_out = os.path.join(self.output_dir, 'toSequence_parsed.csv')
        self.assertFalse(os.path.exists(json_out))
        self.assertFalse(os.path.exists(csv_out))


if __name__ == '__main__':
    unittest.main()
