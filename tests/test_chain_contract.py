import sys
from unittest.mock import MagicMock

# Mock C-extension and heavy dependencies before any imports
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()
sys.modules["numpy"] = MagicMock()
sys.modules["scipy"] = MagicMock()
sys.modules["scipy.io"] = MagicMock()
sys.modules["scipy.io.wavfile"] = MagicMock()

import unittest
import os
import shutil
import tempfile
import json
from unittest.mock import patch
from utils.dna_ui import (
    main as run_batch,
    PersistenceError,
    LedgerLoadError,
    AtomicWriteError,
    DNAProcessingError,
    DNAStatus
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

        # Create valid volume rule
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "amp": {"min": 0, "max": 1000, "pad": 4, "description": "Absolute amp"},
                    "lr": {"min": 0, "max": 100, "pad": 3, "description": "Left-channel dominance"},
                    "sur": {"min": 0, "max": 10, "pad": 2, "description": "Surround depth"},
                    "head": {"min": 0, "max": 60, "pad": 2, "description": "Headroom"}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_happy_path_contract(self):
        """Verify contract happy path: inputs parsed, outputs written, ledger updated."""
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna}\n")

        run_batch(correlation_id="test_corr_123", actor_id="test_actor")

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        csv_out = os.path.join(self.output_dir, 'toSequence_parsed.csv')

        self.assertTrue(os.path.exists(json_out))
        self.assertTrue(os.path.exists(csv_out))
        self.assertTrue(os.path.exists(self.ledger_file))

        with open(json_out, 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]['dna_sequence'], dna)

        with open(self.ledger_file, 'r') as f:
            ledger = json.load(f)
            self.assertIn(dna, ledger)
            self.assertEqual(ledger[dna]['terminal_outcome'], DNAStatus.SUCCESS)

    def test_double_invocation_contract(self):
        """Verify contract idempotency on double invocation."""
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna}\n")

        run_batch(correlation_id="test_corr_1", actor_id="test_actor")

        # Second run with same DNA
        with open(self.input_file, 'w') as f:
            f.write(f"{dna}\n")

        run_batch(correlation_id="test_corr_2", actor_id="test_actor")

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)
            # Should NOT duplicate entry
            self.assertEqual(len(data), 1)

    def test_corrupted_ledger_raises_ledger_load_error(self):
        """Verify that a corrupted ledger file causes a typed LedgerLoadError."""
        with open(self.ledger_file, 'w') as f:
            f.write("{ INVALID JSON")

        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna}\n")

        with self.assertRaises(LedgerLoadError):
            run_batch()

    def test_persistence_failure_rollback(self):
        """Verify that an AtomicWriteError raises on IO crash during atomic persist."""
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna}\n")

        with patch('json.dump', side_effect=IOError("Disk Full")):
            with self.assertRaises(AtomicWriteError):
                run_batch()

if __name__ == '__main__':
    unittest.main()
