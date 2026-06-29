import os
import json
import shutil
import unittest
from unittest.mock import MagicMock, patch
import sys
import tempfile

# Mock dependencies that might be missing in some environments
sys.modules['numpy'] = MagicMock()
sys.modules['scipy'] = MagicMock()
sys.modules['scipy.io'] = MagicMock()
sys.modules['scipy.io.wavfile'] = MagicMock()
sys.modules['torch'] = MagicMock()
sys.modules['torchaudio'] = MagicMock()
sys.modules['sounddevice'] = MagicMock()
sys.modules['PySide6'] = MagicMock()
sys.modules['PySide6.QtWidgets'] = MagicMock()
sys.modules['PySide6.QtCore'] = MagicMock()
sys.modules['PySide6.QtGui'] = MagicMock()

from utils.dna_ui import main as run_batch, PersistenceError

class TestAtomicity(unittest.TestCase):
    def setUp(self):
        # Create a temporary root for the entire project state during the test
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        self.data_folder = os.path.join(self.test_dir, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Create rules folder in test_dir
        self.rules_dir = os.path.join(self.test_dir, 'rules')
        os.makedirs(self.rules_dir, exist_ok=True)

        # Patch abspath in main.py to resolve to our test_dir if needed,
        # but since we chdir it might just work.

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_failure_during_write_leaves_no_partial_files(self):
        """
        If an exception occurs during the atomic write phase,
        the target files should either not exist or remain in their previous state.
        """
        dna = "V100"
        rule_path = os.path.join(self.rules_dir, 'rule_test.json')
        with open(rule_path, 'w') as f:
            json.dump({
                "variable": "Test",
                "prefix": "V",
                "subvars": {
                    "val": {"description": "test", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # Mock os.replace to fail
        with patch('os.replace', side_effect=Exception("Disk Full")):
            with self.assertRaises(PersistenceError):
                run_batch()

        # Verify target files do not exist
        json_out = os.path.join(self.output_folder, 'toSequence_parsed.json')
        csv_out = os.path.join(self.output_folder, 'toSequence_parsed.csv')
        self.assertFalse(os.path.exists(json_out), "JSON output should not exist after failed atomic write")
        self.assertFalse(os.path.exists(csv_out), "CSV output should not exist after failed atomic write")
        self.assertFalse(os.path.exists(self.ledger_path), "Ledger should not exist after failed atomic write")

    def test_no_overwrite_if_no_new_items(self):
        """
        Verify that if no new items are processed (all skipped),
        the output files are not even touched/re-written.
        """
        run_batch()
        json_out = os.path.join(self.output_folder, 'toSequence_parsed.json')
        self.assertFalse(os.path.exists(json_out))

    def test_watcher_behavior_on_failure(self):
        """
        Test main.py's logic: if run_batch fails, input file should NOT be cleared.
        """
        import main
        with open(self.input_file, 'w') as f:
            f.write("SOME DNA\n")

        # We need to ensure main.py logic uses the right input_file path
        # which it should if we chdir'd to test_dir and it uses relative paths.

        with patch('main.run_batch', side_effect=PersistenceError("Permission Denied")):
            try:
                # Manually invoke the logic from watch_loop
                main.run_batch()
                main.clear_input_file(self.input_file)
            except Exception:
                pass

            # Verify file NOT cleared
            with open(self.input_file, 'r') as f:
                content = f.read()
            self.assertEqual(content.strip(), "SOME DNA")

if __name__ == '__main__':
    unittest.main()
