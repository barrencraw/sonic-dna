import sys
from unittest.mock import MagicMock

# Mock GUI dependencies before import
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

        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "master": {"description": "master volume", "min": 0, "max": 999, "pad": 3},
                    "bus_a": {"description": "bus a volume", "min": 0, "max": 999, "pad": 3},
                    "bus_b": {"description": "bus b volume", "min": 0, "max": 999, "pad": 3},
                    "headroom": {"description": "headroom", "min": 0, "max": 99, "pad": 2}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_happy_path(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna}\n")

        run_batch(correlation_id="contract-test-1")

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertTrue(os.path.exists(json_out))
        with open(json_out, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['dna_sequence'], dna)

        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)
        self.assertIn(dna, ledger_data['ledger'])
        self.assertEqual(ledger_data['ledger'][dna]['terminal_outcome'], 'success')

    def test_double_invocation_idempotency(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna}\n")

        run_batch(correlation_id="contract-test-2a")
        run_batch(correlation_id="contract-test-2b")

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1, "Double invocation should not create duplicate entries")

    def test_persistence_failure(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna}\n")

        with patch('os.replace', side_effect=OSError("Atomic rename failed")):
            with self.assertRaises(PersistenceError):
                run_batch(correlation_id="contract-test-3")

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertFalse(os.path.exists(json_out))

if __name__ == '__main__':
    unittest.main()
