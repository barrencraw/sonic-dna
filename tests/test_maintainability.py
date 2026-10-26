import sys
from unittest.mock import MagicMock

# Mock non-installed heavy dependencies before imports
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6
sys.modules["numpy"] = MagicMock()
sys.modules["scipy"] = MagicMock()
sys.modules["scipy.io"] = MagicMock()
sys.modules["scipy.io.wavfile"] = MagicMock()
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

import unittest
import os
import shutil
import tempfile
import json
import inspect
from io import StringIO
from unittest.mock import patch
from utils.dna_calculator import DNACalculator
from utils.dna_ui import (
    run_batch,
    DNAStatus,
    DNAProcessingError,
    InputReadError,
    PersistenceError,
    LedgerSaveError,
    AtomicWriteError
)

class TestMaintainability(unittest.TestCase):
    def test_naming_alignment_dna_sequence(self):
        """Verify that DNACalculator.parse parameter is canonicalized to 'dna_sequence'."""
        sig = inspect.signature(DNACalculator.parse)
        self.assertIn("dna_sequence", sig.parameters)
        self.assertNotIn("dna_string", sig.parameters)

    def test_typed_exception_hierarchy(self):
        """Verify typed exceptions inherit correctly from base classes."""
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_dna_status_enum_values(self):
        """Verify DNAStatus enum explicit string values."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")

    def test_structured_logging_fields(self):
        """Verify structured JSON telemetry log schema during batch execution."""
        test_dir = tempfile.mkdtemp()
        try:
            raw_dir = os.path.join(test_dir, 'data', 'raw')
            output_dir = os.path.join(test_dir, 'data', 'output')
            rules_dir = os.path.join(test_dir, 'rules')
            os.makedirs(raw_dir)
            os.makedirs(output_dir)
            os.makedirs(rules_dir)

            input_file = os.path.join(raw_dir, 'toSequence.txt')
            with open(input_file, 'w') as f:
                f.write("V100\n")

            rule_file = os.path.join(rules_dir, 'rules_Volume.json')
            with open(rule_file, 'w') as f:
                json.dump({
                    "variable": "Volume",
                    "prefix": "V",
                    "subvars": {
                        "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                    }
                }, f)

            old_cwd = os.getcwd()
            os.chdir(test_dir)
            try:
                captured_stdout = StringIO()
                with patch('sys.stdout', captured_stdout):
                    run_batch(correlation_id="test-corr-id-1234")

                output = captured_stdout.getvalue()
                log_lines = [line for line in output.splitlines() if line.startswith("JSON_LOG: ")]
                self.assertGreater(len(log_lines), 0, "Structured JSON logs should be emitted")

                mandatory_fields = {
                    "timestamp",
                    "correlation_id",
                    "actor_id",
                    "chain_name",
                    "step",
                    "outcome",
                    "latency_ms",
                    "idempotency_key",
                    "outcome_detail"
                }

                for log_line in log_lines:
                    json_str = log_line.replace("JSON_LOG: ", "", 1)
                    log_obj = json.loads(json_str)
                    for field in mandatory_fields:
                        self.assertIn(field, log_obj, f"Field '{field}' missing from structured log")
                    self.assertEqual(log_obj["correlation_id"], "test-corr-id-1234")
            finally:
                os.chdir(old_cwd)
        finally:
            shutil.rmtree(test_dir)

if __name__ == '__main__':
    unittest.main()
