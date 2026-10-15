import sys
from unittest.mock import MagicMock

# Mock GUI / audio dependencies
sys.modules["PySide6"] = MagicMock()
sys.modules["PySide6.QtWidgets"] = MagicMock()
sys.modules["PySide6.QtCore"] = MagicMock()
sys.modules["PySide6.QtGui"] = MagicMock()
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

import os
import json
import shutil
import tempfile
import unittest
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

        # Mock rule file for Volume ('VOL') prefix
        rule_path = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(rule_path, 'w', encoding='utf-8') as f:
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

    def test_happy_path_parsing_and_contract_fulfillment(self):
        """Happy path: valid sequence processed, outputs and ledger updated."""
        dna = "VOL100"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch()

        self.assertTrue(os.path.exists(self.json_out))
        self.assertTrue(os.path.exists(self.csv_out))
        self.assertTrue(os.path.exists(self.ledger_file))

        with open(self.json_out, 'r', encoding='utf-8') as f:
            parsed = json.load(f)
            self.assertEqual(len(parsed), 1)
            self.assertEqual(parsed[0]['dna'], dna)

        with open(self.ledger_file, 'r', encoding='utf-8') as f:
            ledger = json.load(f)
            self.assertIn(dna, ledger)
            self.assertEqual(ledger[dna]['terminal_outcome'], 'success')

    def test_double_invocation_idempotency(self):
        """Adversarial: re-running batch on identical DNA sequence produces no duplicate side-effects."""
        dna = "VOL100"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch()

        # Re-trigger with same DNA
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.json_out, 'r', encoding='utf-8') as f:
            parsed = json.load(f)
            self.assertEqual(len(parsed), 1, "Duplicate DNA sequence must not be re-appended to parsed output")

    def test_persistence_failure_atomicity_boundary(self):
        """Infra failure: failure during atomic replace raises PersistenceError and preserves prior state."""
        dna = "VOL100"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        with patch('os.replace', side_effect=OSError("Disk write error")):
            with self.assertRaises(PersistenceError):
                run_batch()

        self.assertFalse(os.path.exists(self.json_out))
        self.assertFalse(os.path.exists(self.csv_out))

if __name__ == '__main__':
    unittest.main()
