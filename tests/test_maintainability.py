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
sys.modules["scipy.io.wavfile"] = MagicMock()

import unittest
import os
import shutil
import tempfile
import json
import io
import uuid
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch

class TestMaintainability(unittest.TestCase):
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

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_structured_logging_emitted(self):
        """Verify that log_structured produces expected JSON logs."""
        correlation_id = uuid.uuid4()

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id=correlation_id)

        output = f.getvalue()
        log_lines = [line for line in output.splitlines() if line.startswith("JSON_LOG: ")]

        self.assertTrue(len(log_lines) >= 2, f"Expected at least 2 log lines, got {len(log_lines)}")

        # Check first log (dedupe miss)
        first_log_raw = log_lines[0].replace("JSON_LOG: ", "")
        first_log = json.loads(first_log_raw)
        self.assertEqual(first_log['correlation_id'], str(correlation_id))
        self.assertEqual(first_log['step'], "dedupe")
        self.assertEqual(first_log['outcome'], "miss")

        # Check last log (batch_complete)
        last_log_raw = log_lines[-1].replace("JSON_LOG: ", "")
        last_log = json.loads(last_log_raw)
        self.assertEqual(last_log['correlation_id'], str(correlation_id))
        self.assertEqual(last_log['step'], "batch_complete")
        self.assertEqual(last_log['outcome'], "success")
        self.assertEqual(last_log['processed_count'], 1)

if __name__ == '__main__':
    unittest.main()
