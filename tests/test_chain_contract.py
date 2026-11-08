import sys
from unittest.mock import MagicMock

# Mock dependencies before any imports
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

        # Volume rule
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_happy_path_contract(self):
        """Verify happy path adheres to contract: valid parse, outputs created, ledger updated."""
        dna = "VOL100"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna}\n")

        run_batch(correlation_id="test-cid-1", actor_id="test_runner")

        self.assertTrue(os.path.exists(self.json_out))
        self.assertTrue(os.path.exists(self.csv_out))
        self.assertTrue(os.path.exists(self.ledger_file))

        with open(self.json_out, 'r') as f:
            json_data = json.load(f)
            self.assertEqual(len(json_data), 1)
            self.assertEqual(json_data[0]['dna'], dna)

        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)
            self.assertIn(dna, ledger_data)
            self.assertEqual(ledger_data[dna]['terminal_outcome'], 'success')

    def test_adversarial_double_invocation_idempotency(self):
        """Verify contract invariant: double invocation does not duplicate output entries."""
        dna = "VOL100"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna}\n")

        run_batch(correlation_id="test-cid-2a")

        with open(self.json_out, 'r') as f:
            self.assertEqual(len(json.load(f)), 1)

        # Re-invoke with the same sequence
        with open(self.input_file, 'w') as f:
            f.write(f"{dna}\n")

        run_batch(correlation_id="test-cid-2b")

        with open(self.json_out, 'r') as f:
            self.assertEqual(len(json.load(f)), 1, "Duplicate entry created on double invocation")

    def test_adversarial_persistence_failure_boundary(self):
        """Verify atomicity: if writing fails mid-way, PersistenceError is raised and no partial writes occur."""
        dna = "VOL200"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna}\n")

        with patch('os.replace', side_effect=OSError("Disk write failed")):
            with self.assertRaises(PersistenceError):
                run_batch(correlation_id="test-cid-3")

        # Output files must not exist because replace failed
        self.assertFalse(os.path.exists(self.json_out))
        self.assertFalse(os.path.exists(self.csv_out))

if __name__ == '__main__':
    unittest.main()
