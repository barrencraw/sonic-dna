import sys
import unittest
import os
import shutil
import tempfile
import json
from unittest.mock import patch, MagicMock

# Mock non-existent libraries for testing environment BEFORE any other imports
sys.modules["numpy"] = MagicMock()
sys.modules["scipy"] = MagicMock()
sys.modules["scipy.io.wavfile"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()
sys.modules["PySide6"] = MagicMock()
sys.modules["PySide6.QtWidgets"] = MagicMock()
sys.modules["PySide6.QtCore"] = MagicMock()
sys.modules["PySide6.QtGui"] = MagicMock()

# Also mock ui.main_window and ui.music_panel to avoid their imports
sys.modules["ui.main_window"] = MagicMock()
sys.modules["ui.music_panel"] = MagicMock()

from utils.dna_ui import main as run_batch, PersistenceError

class TestDNABatchHardened(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')

        # Mock a rule file for Volume
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "V",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_happy_path_and_idempotency(self):
        # 1. Process one DNA string
        with open(self.input_file, 'w') as f:
            f.write("V100\n")

        run_batch(correlation_id="test-1", actor_id="test-actor")

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]['dna'], 'V100')

        with open(self.ledger_file, 'r') as f:
            ledger = json.load(f)
            self.assertIn('V100', ledger)
            self.assertEqual(ledger['V100']['terminal_outcome'], 'SUCCESS')

        # 2. Process same DNA + a new one
        with open(self.input_file, 'w') as f:
            f.write("V100\nV200\n")

        run_batch(correlation_id="test-2", actor_id="test-actor")

        with open(json_out, 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data), 2, "Should have 2 unique entries")
            self.assertEqual(data[1]['dna'], 'V200')

        with open(self.ledger_file, 'r') as f:
            ledger = json.load(f)
            self.assertIn('V100', ledger)
            self.assertIn('V200', ledger)

    def test_main_does_not_clear_on_failure(self):
        # We need to import main after mocking its dependencies
        if 'main' in sys.modules:
            del sys.modules['main']
        import main

        with open(self.input_file, 'w') as f:
            f.write("V100\n")

        # Mock __file__ in main to point to our test_dir so os.path.dirname works
        # and patch run_batch inside the main module
        with patch('main.__file__', os.path.join(self.test_dir, 'main.py')):
            with patch('main.run_batch', side_effect=PersistenceError("Failed")):
                with self.assertRaises(SystemExit):
                    main.process_once()

        # Verify file still has content
        with open(self.input_file, 'r') as f:
            self.assertEqual(f.read().strip(), "V100")

if __name__ == '__main__':
    unittest.main()
