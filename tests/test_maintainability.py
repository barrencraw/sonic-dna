import inspect
import json
import unittest
import sys
from unittest.mock import patch, MagicMock

# Ensure project modules can be loaded even if headless or without full env
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

from utils.dna_ui import (
    run_batch,
    log_structured,
    DNAProcessingError,
    RuleLoadError,
    InputReadError,
    PersistenceError,
    LedgerSaveError,
    BatchResult
)

class TestMaintainability(unittest.TestCase):
    def test_run_batch_signature(self):
        """Verify that run_batch has correlation_id parameter."""
        sig = inspect.signature(run_batch)
        self.assertIn('correlation_id', sig.parameters)
        # Verify default value of correlation_id is None
        self.assertIsNone(sig.parameters['correlation_id'].default)

    def test_error_taxonomy(self):
        """Verify the correct inheritance hierarchy for custom exceptions."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))

    def test_structured_logging_keys(self):
        """Verify that log_structured outputs correct keys and prefix."""
        captured_logs = []
        def mock_print(message):
            captured_logs.append(message)

        with patch('builtins.print', side_effect=mock_print):
            log_structured(
                correlation_id="test-corr-123",
                step="test_step",
                outcome="success",
                latency_ms=45,
                actor_id="test_actor",
                idempotency_key="V100",
                outcome_detail="Everything fine"
            )

        self.assertEqual(len(captured_logs), 1)
        log_line = captured_logs[0]
        self.assertTrue(log_line.startswith("JSON_LOG:"))

        # Extract JSON
        json_part = log_line[len("JSON_LOG:"):]
        log_dict = json.loads(json_part)

        # Check for mandatory keys
        mandatory_keys = {
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
        for key in mandatory_keys:
            self.assertIn(key, log_dict)

        # Check values
        self.assertEqual(log_dict["correlation_id"], "test-corr-123")
        self.assertEqual(log_dict["step"], "test_step")
        self.assertEqual(log_dict["outcome"], "success")
        self.assertEqual(log_dict["latency_ms"], 45)
        self.assertEqual(log_dict["actor_id"], "test_actor")
        self.assertEqual(log_dict["idempotency_key"], "V100")
        self.assertEqual(log_dict["outcome_detail"], "Everything fine")
        self.assertEqual(log_dict["chain_name"], "dna_batch_parser")
        self.assertTrue(log_dict["timestamp"].endswith("Z"))

    def test_batch_result_properties(self):
        """Verify that BatchResult is correctly formed and contains expected attributes."""
        res = BatchResult(status="SUCCESS", new_processed_count=5, total_in_ledger=10, error=None)
        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(res.new_processed_count, 5)
        self.assertEqual(res.total_in_ledger, 10)
        self.assertIsNone(res.error)

if __name__ == '__main__':
    unittest.main()
