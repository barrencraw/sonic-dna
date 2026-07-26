import os
import sys
import shutil
import unittest
import tempfile
from unittest.mock import patch, MagicMock

# Mock PySide6 GUI dependencies so we can run tests headlessly
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

import main
from utils.dna_ui import run_batch, DNAProcessingError, RuleLoadError, PersistenceError

class TestWatcherIntegration(unittest.TestCase):
    def setUp(self):
        # Create a temporary sandbox directory structure
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("VOL08900750712\n")

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Patch main.__file__ so it resolves directories correctly relative to sandbox
        self.old_main_file = main.__file__
        main.__file__ = os.path.join(self.test_dir, 'main.py')

    def tearDown(self):
        main.__file__ = self.old_main_file
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_watcher_loop_clears_on_success(self):
        """Verify that watch_loop clears input file when run_batch succeeds."""
        call_count = 0
        def mock_read(path):
            nonlocal call_count
            if call_count == 0:
                call_count += 1
                return "VOL08900750712\n"
            else:
                raise KeyboardInterrupt()

        with patch('main.run_batch') as mock_run:
            with patch('main.read_raw_contents', side_effect=mock_read):
                main.watch_loop()
                mock_run.assert_called_once()

                # Input file should be cleared (empty)
                with open(self.input_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.assertEqual(content, "")

    def test_process_once_retains_on_failure(self):
        """Verify that process_once does NOT clear input file when run_batch fails."""
        with patch('main.run_batch', side_effect=DNAProcessingError("Failed simulated run")):
            with self.assertRaises(SystemExit) as cm:
                main.process_once()

            # Should exit with code 1
            self.assertEqual(cm.exception.code, 1)

            # Input file should STILL contain original content
            with open(self.input_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
            self.assertEqual(content, "VOL08900750712")

if __name__ == '__main__':
    unittest.main()
