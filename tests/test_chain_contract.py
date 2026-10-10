import sys
from unittest.mock import MagicMock

# Mock native C dependencies before imports
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

import unittest
import os
import shutil
import tempfile
import json
from unittest.mock import patch
from utils.dna_ui import run_batch, AtomicWriteError, DNAProcessingError, PersistenceError

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

        # Mock Volume rule file
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_happy_path_and_telemetry(self):
        """Verify happy path batch parsing and schema output compatibility."""
        sequence = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(sequence + "\n")

        with patch('builtins.print') as mock_print:
            run_batch(correlation_id="test-correlation-123")

            # Check that structured telemetry was logged
            printed_logs = [call[0][0] for call in mock_print.call_args_list if call[0] and isinstance(call[0][0], str)]
            json_logs = [p for p in printed_logs if p.startswith("JSON_LOG:")]
            self.assertTrue(len(json_logs) > 0)
            self.assertIn("test-correlation-123", json_logs[0])

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertTrue(os.path.exists(json_out))
        with open(json_out, 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]['dna'], sequence)
            self.assertEqual(data[0]['dna_sequence'], sequence)

    def test_double_invocation_idempotency(self):
        """Verify second execution with identical key does not create duplicate entries."""
        sequence = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(sequence + "\n")

        run_batch()

        # Re-trigger with same key
        with open(self.input_file, 'w') as f:
            f.write(sequence + "\n")

        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1, "Duplicate key must not create duplicate outputs")

    def test_adversarial_persistence_failure(self):
        """Verify atomic write failure raises AtomicWriteError without mutating destination files."""
        sequence = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(sequence + "\n")

        with patch('os.replace', side_effect=OSError("Disk write error")):
            with self.assertRaises(AtomicWriteError):
                run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertFalse(os.path.exists(json_out), "Destination file must not exist after failed replace")

if __name__ == '__main__':
    unittest.main()
