import sys
from unittest.mock import MagicMock, patch

# Mock UI / heavy modules before importing
sys.modules["PySide6"] = MagicMock()
sys.modules["PySide6.QtWidgets"] = MagicMock()
sys.modules["PySide6.QtCore"] = MagicMock()
sys.modules["PySide6.QtGui"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

import unittest
import os
import json
import shutil
import tempfile
import inspect
from utils.dna_calculator import DNACalculator
from utils.dna_ui import (
    main as run_batch,
    DNAStatus,
    DNAProcessingError,
    InputReadError,
    LedgerSaveError,
    AtomicWriteError,
    log_structured
)

class TestMaintainability(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        # Create sample Volume rule
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
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

    def test_naming_alignment(self):
        """Verify DNACalculator.parse parameter is named `dna_sequence`."""
        sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', sig.parameters, "DNACalculator.parse parameter must be `dna_sequence`")

    def test_typed_exception_hierarchy(self):
        """Verify exception classes inherit properly from DNAProcessingError."""
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerSaveError, DNAProcessingError))
        self.assertTrue(issubclass(AtomicWriteError, DNAProcessingError))

    def test_dna_status_enum(self):
        """Verify DNAStatus values match terminal outcome specs."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")

    def test_structured_logging_keys(self):
        """Verify log_structured emits all required standard observability keys."""
        with patch('builtins.print') as mock_print:
            log_structured(
                correlation_id="test-corr-123",
                chain_name="test_chain",
                step="test_step",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=12.34,
                actor_id="test_actor",
                idempotency_key="VOL100"
            )

            mock_print.assert_called_once()
            log_line = mock_print.call_args[0][0]
            self.assertTrue(log_line.startswith("JSON_LOG: "))

            payload = json.loads(log_line.replace("JSON_LOG: ", ""))
            expected_keys = {
                "timestamp", "correlation_id", "actor_id", "chain_name",
                "step", "outcome", "latency_ms", "idempotency_key"
            }
            self.assertEqual(set(payload.keys()), expected_keys)
            self.assertEqual(payload["correlation_id"], "test-corr-123")
            self.assertEqual(payload["chain_name"], "test_chain")
            self.assertEqual(payload["step"], "test_step")
            self.assertEqual(payload["outcome"], "success")
            self.assertEqual(payload["actor_id"], "test_actor")
            self.assertEqual(payload["idempotency_key"], "VOL100")

    def test_backward_compatibility_output_keys(self):
        """Verify batch output includes both legacy `dna` and canonical `dna_sequence` keys."""
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(input_file, 'w') as f:
            f.write("VOL100\n")

        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertTrue(os.path.exists(json_out))

        with open(json_out, 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)
            entry = data[0]
            self.assertIn('dna', entry)
            self.assertIn('dna_sequence', entry)
            self.assertEqual(entry['dna'], 'VOL100')
            self.assertEqual(entry['dna_sequence'], 'VOL100')

if __name__ == '__main__':
    unittest.main()
