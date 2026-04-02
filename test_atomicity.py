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
from utils.dna_ui import main as run_batch, PersistenceError

class TestAtomicity(unittest.TestCase):
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
        self.json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.csv_out = os.path.join(self.output_dir, 'toSequence_parsed.csv')

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_successful_parsing(self):
        """Verify that parsing works correctly under normal conditions."""
        run_batch()

        self.assertTrue(os.path.exists(self.json_out))
        self.assertTrue(os.path.exists(self.csv_out))
        self.assertTrue(os.path.exists(self.ledger_path))

        with open(self.json_out, 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]['dna'], 'V100')

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
            self.assertIn('V100', ledger)
            self.assertEqual(ledger['V100']['terminal_outcome'], 'success')

    def test_crash_during_write(self):
        """Simulate a crash during writing. No output files should be created."""
        with patch('json.dump', side_effect=IOError("Disk Full")):
            with self.assertRaises(PersistenceError):
                run_batch()

        self.assertFalse(os.path.exists(self.json_out))
        self.assertFalse(os.path.exists(self.csv_out))
        self.assertFalse(os.path.exists(self.ledger_path))

    def test_crash_during_rename(self):
        """Simulate a crash/failure during the atomic rename. No output files should be created/updated."""
        with patch('os.replace', side_effect=OSError("Permission Denied")):
            with self.assertRaises(PersistenceError):
                run_batch()

        self.assertFalse(os.path.exists(self.json_out))
        self.assertFalse(os.path.exists(self.csv_out))
        self.assertFalse(os.path.exists(self.ledger_path))

    def test_watcher_behavior_on_failure(self):
        """Test main.py's logic: if run_batch fails, input file should NOT be cleared."""
        # Force import after mocks
        if 'main' in sys.modules:
            del sys.modules['main']
        import main

        # Need to ensure main's idea of current directory is our test_dir
        with patch('os.path.dirname', return_value=self.test_dir):
            with patch('os.path.abspath', return_value=self.test_dir):
                # Mock run_batch to fail with PersistenceError
                with patch('main.run_batch', side_effect=PersistenceError("Failed")):
                    with patch('main.clear_input_file') as mock_clear:
                        with self.assertRaises(SystemExit): # process_once calls sys.exit(1) on failure
                            main.process_once()

                        mock_clear.assert_not_called()

        # Verify file still has content
        with open(self.input_file, 'r') as f:
            self.assertEqual(f.read().strip(), "V100")

if __name__ == '__main__':
    unittest.main()
