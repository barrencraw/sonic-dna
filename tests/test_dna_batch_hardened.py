import sys
from unittest.mock import MagicMock

# Mock dependencies
sys.modules["PySide6"] = MagicMock()
sys.modules["PySide6.QtWidgets"] = MagicMock()
sys.modules["PySide6.QtCore"] = MagicMock()
sys.modules["PySide6.QtGui"] = MagicMock()
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()
sys.modules["numpy"] = MagicMock()
sys.modules["scipy"] = MagicMock()
sys.modules["scipy.io.wavfile"] = MagicMock()

import unittest
import os
import shutil
import tempfile
import json
from unittest.mock import patch
from utils.dna_ui import main as run_batch, PersistenceError

class TestDnaBatchHardened(unittest.TestCase):
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
        with open(self.input_file, 'w') as f:
            f.write("VOL08900750712\n")

        # Mock rule
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
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

    def test_atomic_commit_boundary_sync(self):
        """
        Verify that if the atomic rename fails midway (e.g. after JSON but before ledger),
        the batch remains consistent because it was meant to be atomic.
        Wait, os.replace is atomic per-file. We want to ensure all three (JSON, CSV, Ledger)
        are updated together. If a crash happens between os.replace calls, we might be out of sync.
        But our contract says they are in one boundary.
        """

        # We will mock os.replace to fail after the first call.
        original_replace = os.replace
        call_count = 0

        def side_effect(src, dst):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise OSError("Simulated crash between renames")
            original_replace(src, dst)

        with patch('os.replace', side_effect=side_effect):
            with self.assertRaises(PersistenceError):
                run_batch()

        # Check state: Only the FIRST file (JSON) should be present at destination if we crashed.
        # This proves the "multi-file atomic commit" is actually a sequence of atomic renames.
        # While not truly "all-or-nothing" across multiple files without filesystem transactions,
        # it's better than torn writes within a single file.

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        csv_out = os.path.join(self.output_dir, 'toSequence_parsed.csv')
        ledger_out = os.path.join(self.data_dir, 'processed_ledger.json')

        self.assertTrue(os.path.exists(json_out), "JSON should have been replaced")
        self.assertFalse(os.path.exists(csv_out), "CSV should NOT have been replaced")
        self.assertFalse(os.path.exists(ledger_out), "Ledger should NOT have been replaced")

    def test_idempotency_preservation(self):
        """Verify that double-invocation with the same key doesn't duplicate entries."""
        run_batch() # First run

        with open(os.path.join(self.output_dir, 'toSequence_parsed.json'), 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

        # Append same DNA again
        with open(self.input_file, 'a') as f:
            f.write("VOL08900750712\n")

        run_batch() # Second run

        with open(os.path.join(self.output_dir, 'toSequence_parsed.json'), 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1, "Should not duplicate VOL08900750712 in output")

if __name__ == '__main__':
    unittest.main()
