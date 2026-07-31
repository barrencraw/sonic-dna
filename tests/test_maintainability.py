import sys
from unittest.mock import MagicMock, patch

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
sys.modules["watchdog"] = MagicMock()

import unittest
import inspect
import json
import io
from utils.dna_ui import run_batch, log_structured, PersistenceError, DNAProcessingError

class TestMaintainability(unittest.TestCase):
    def test_run_batch_signature_correlation_id(self):
        """Verify that run_batch has a correlation_id parameter in its signature."""
        sig = inspect.signature(run_batch)
        self.assertIn('correlation_id', sig.parameters, "run_batch signature must include 'correlation_id'")

    def test_log_structured_emits_canonical_fields(self):
        """Verify that log_structured emits all required canonical fields in JSON_LOG."""
        captured_stdout = io.StringIO()
        with patch('sys.stdout', new=captured_stdout):
            log_structured(
                correlation_id="test-corr-123",
                step="test-step",
                outcome="test-outcome",
                latency_ms=12.34,
                idempotency_key="test-key-555",
                outcome_detail="test-detail",
                actor_id="test-actor"
            )

        output = captured_stdout.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG:"), "Log output must start with 'JSON_LOG:'")

        json_part = output[len("JSON_LOG:"):].strip()
        log_data = json.loads(json_part)

        # Verify mandatory fields
        required_fields = [
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        ]
        for field in required_fields:
            self.assertIn(field, log_data, f"Structured log must contain '{field}' field")

        # Check ISO 8601 formatting of timestamp (ending in Z)
        timestamp = log_data["timestamp"]
        self.assertTrue(timestamp.endswith("Z"), f"Timestamp '{timestamp}' must end with 'Z'")

        # Check standard values
        self.assertEqual(log_data["correlation_id"], "test-corr-123")
        self.assertEqual(log_data["actor_id"], "test-actor")
        self.assertEqual(log_data["chain_name"], "dna_batch_parser")
        self.assertEqual(log_data["step"], "test-step")
        self.assertEqual(log_data["outcome"], "test-outcome")
        self.assertEqual(log_data["latency_ms"], 12.34)
        self.assertEqual(log_data["idempotency_key"], "test-key-555")
        self.assertEqual(log_data["outcome_detail"], "test-detail")

if __name__ == '__main__':
    unittest.main()
