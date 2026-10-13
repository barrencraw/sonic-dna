import sys
from unittest.mock import MagicMock

# Mock PySide6 and other native C dependencies if needed
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6

import os
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch
from utils.dna_ui import run_batch, PersistenceError, RuleLoadError

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

        # Mock Volume rule file
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w', encoding='utf-8') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "V",
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
        dna = "V100"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch(correlation_id="test_happy_path", actor_id="test_runner")

        # Verify output files
        self.assertTrue(os.path.exists(self.json_output))
        self.assertTrue(os.path.exists(self.csv_output))

        with open(self.json_output, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]['dna'], dna)

        with open(self.ledger_file, 'r', encoding='utf-8') as f:
            ledger = json.load(f)
            self.assertIn(dna, ledger)
            self.assertEqual(ledger[dna]['terminal_outcome'], 'success')

    def test_double_invocation_idempotency_contract(self):
        dna = "V100"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch(correlation_id="test_run_1", actor_id="test_runner")

        # Second run with same DNA sequence
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch(correlation_id="test_run_2", actor_id="test_runner")

        # Output file should still have exactly 1 record
        with open(self.json_output, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)

    def test_persistence_failure_adversarial_contract(self):
        dna = "V200"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        # Simulate atomic rename failure
        with patch('os.replace', side_effect=OSError("Disk write error")):
            with self.assertRaises(PersistenceError):
                run_batch(correlation_id="test_persistence_fail", actor_id="test_runner")

        # Output files must not exist due to atomicity boundary failure
        self.assertFalse(os.path.exists(self.json_output))
        self.assertFalse(os.path.exists(self.csv_output))

if __name__ == '__main__':
    unittest.main()
