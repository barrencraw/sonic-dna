import sys
from unittest.mock import MagicMock

sys.modules.setdefault("PySide6", MagicMock())
sys.modules.setdefault("PySide6.QtWidgets", MagicMock())
sys.modules.setdefault("PySide6.QtCore", MagicMock())
sys.modules.setdefault("PySide6.QtGui", MagicMock())

import unittest
import os
import shutil
import tempfile
import json
from unittest.mock import patch
from utils.dna_ui import (
    run_batch,
    PersistenceError,
    LedgerLoadError,
    AtomicWriteError
)

class TestChainContract(unittest.TestCase):
    def setUp(self):
        self.old_cwd = os.getcwd()
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)

        # Copy actual rules folder from project root
        actual_rules = os.path.join(self.old_cwd, 'rules')
        if os.path.exists(actual_rules):
            shutil.copytree(actual_rules, self.rules_dir, dirs_exist_ok=True)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')

        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_happy_path_processing(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertTrue(os.path.exists(json_out))

        with open(json_out, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]['dna'], dna)
            self.assertEqual(data[0]['dna_sequence'], dna)

        with open(self.ledger_file, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)
            ledger_map = ledger_data.get('ledger', ledger_data)
            self.assertIn(dna, ledger_map)
            self.assertEqual(ledger_map[dna]['terminal_outcome'], 'success')

    def test_double_invocation_idempotency(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch()
        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1, "Should not duplicate entries in output file")

    def test_persistence_failure_rollback(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        with patch('os.replace', side_effect=OSError("Disk write error")):
            with self.assertRaises(PersistenceError):
                run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertFalse(os.path.exists(json_out), "Output file should not exist on persistence failure")

    def test_corrupted_ledger_failure(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        with open(self.ledger_file, 'w', encoding='utf-8') as f:
            f.write("CORRUPTED_JSON_{{{")

        with self.assertRaises(LedgerLoadError):
            run_batch()

if __name__ == '__main__':
    unittest.main()
