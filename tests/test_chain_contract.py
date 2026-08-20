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

import unittest
import os
import shutil
import tempfile
import json
import io
from unittest.mock import patch
from utils.dna_ui import main as run_batch, PersistenceError, DNAProcessingError

class TestChainContract(unittest.TestCase):
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

        # Valid Volume DNA length = "VOL" + 3 + 3 + 3 + 1 = 13 chars (e.g. VOL0890070501)
        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(self.input_file, 'w') as f:
            f.write("VOL0890070501\n")

        # Mock Volume rule file
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3},
                    "fade_in": {"description": "fade in duration", "min": 0, "max": 999, "pad": 3},
                    "fade_out": {"description": "fade out duration", "min": 0, "max": 999, "pad": 3},
                    "curve": {"description": "volume curve type", "min": 0, "max": 9, "pad": 1}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_happy_path_and_telemetry(self):
        """Verify happy path batch execution produces atomic outputs, ledger entries, and telemetry logs."""
        captured_output = io.StringIO()
        with patch('sys.stdout', captured_output):
            run_batch(correlation_id="test-corr-123")

        logs = captured_output.getvalue()
        self.assertIn("[Chain:DNA_Batch] [START] correlation_id=test-corr-123 total_sequences=1", logs)
        self.assertIn("[Chain:DNA_Batch] [STEP:Idempotency] key=VOL0890070501 dedupe_hit=False", logs)
        self.assertIn("[Chain:DNA_Batch] [END] outcome=SUCCESS new_processed=1 total_ledger=1", logs)

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        csv_out = os.path.join(self.output_dir, 'toSequence_parsed.csv')
        ledger_out = os.path.join(self.data_dir, 'processed_ledger.json')

        self.assertTrue(os.path.exists(json_out))
        self.assertTrue(os.path.exists(csv_out))
        self.assertTrue(os.path.exists(ledger_out))

        with open(ledger_out, 'r') as f:
            ledger = json.load(f)
            self.assertIn("VOL0890070501", ledger)
            self.assertEqual(ledger["VOL0890070501"]["terminal_outcome"], "success")

    def test_double_invocation_adversarial_idempotency(self):
        """Verify second invocation with identical DNA key results in a deduplication hit and no duplicate outputs."""
        run_batch(correlation_id="run-1")

        captured_output = io.StringIO()
        with patch('sys.stdout', captured_output):
            run_batch(correlation_id="run-2")

        logs = captured_output.getvalue()
        self.assertIn("[Chain:DNA_Batch] [STEP:Idempotency] key=VOL0890070501 dedupe_hit=True terminal_outcome=success", logs)
        self.assertIn("[Chain:DNA_Batch] [END] outcome=SUCCESS new_processed=0 total_ledger=1", logs)

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)

    def test_infra_failure_atomicity_rollback(self):
        """Simulate persistence failure during atomic rename. Ensure outputs are not partially created/corrupted."""
        with patch('os.replace', side_effect=OSError("Disk write error")):
            with self.assertRaises(PersistenceError):
                run_batch(correlation_id="run-fail")

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        csv_out = os.path.join(self.output_dir, 'toSequence_parsed.csv')

        self.assertFalse(os.path.exists(json_out))
        self.assertFalse(os.path.exists(csv_out))

if __name__ == '__main__':
    unittest.main()
