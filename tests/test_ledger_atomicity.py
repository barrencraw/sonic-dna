import sys
from unittest.mock import MagicMock

# Mock dependencies before any imports
try:
    from PySide6.QtWidgets import QApplication
except ImportError:
    mock_pyside6 = MagicMock()
    sys.modules["PySide6"] = mock_pyside6
    sys.modules["PySide6.QtWidgets"] = mock_pyside6
    sys.modules["PySide6.QtCore"] = mock_pyside6
    sys.modules["PySide6.QtGui"] = mock_pyside6

sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

# Mock numpy and scipy if not available
try:
    import numpy as np
except ImportError:
    mock_np = MagicMock()
    sys.modules["numpy"] = mock_np
    try:
        import scipy
    except ImportError:
        mock_scipy = MagicMock()
        sys.modules["scipy"] = mock_scipy
        sys.modules["scipy.io"] = mock_scipy
        sys.modules["scipy.io.wavfile"] = mock_scipy

import unittest
import os
import shutil
import tempfile
import json
from unittest.mock import patch, MagicMock
from utils.dna_ui import main as run_batch, PersistenceError, DNAProcessingError

class TestLedgerAtomicity(unittest.TestCase):
    def setUp(self):
        # Create a temporary project structure
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(self.input_file, 'w') as f:
            f.write("V100\n")

        # Mock a rule file
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "V",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_ledger_not_updated_on_failure(self):
        """Verify that the ledger remains unchanged (or non-existent) if a crash occurs during persistence."""

        # Simulate failure during the atomic write of JSON
        # We target open() inside the Persistence block
        original_open = open

        def mocked_open(file, *args, **kwargs):
            if 'toSequence_parsed.json' in str(file) and 'w' in str(args[0]):
                raise IOError("Simulation: Disk Full during JSON write")
            return original_open(file, *args, **kwargs)

        with patch('builtins.open', side_effect=mocked_open):
            with self.assertRaises(PersistenceError):
                run_batch()

        # Ledger should not exist if it's a fresh run, or should be unchanged.
        self.assertFalse(os.path.exists(self.ledger_path), "Ledger should NOT have been created if JSON write failed")

    def test_ledger_atomic_with_outputs(self):
        """Verify that if all writes succeed, ledger and outputs exist together."""
        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertTrue(os.path.exists(json_out))
        self.assertTrue(os.path.exists(self.ledger_path))

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
            self.assertIn('V100', ledger)

if __name__ == '__main__':
    unittest.main()
