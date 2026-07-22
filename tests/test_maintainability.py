import sys
from unittest.mock import MagicMock

# Mock dependencies before any imports to ensure headless robustness
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

import unittest
import inspect
import json
import re
from unittest.mock import patch
from utils.dna_ui import DNAStatus, process_single_dna, log_structured, run_batch

class TestMaintainability(unittest.TestCase):
    def test_dna_status_enum_values(self):
        """Ensure DNAStatus uses precise lowercase outcomes for backward compatibility."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_function_signature_naming_alignment(self):
        """Ensure canonical naming conventions (dna_sequence, correlation_id) are enforced."""
        # Check process_single_dna signature
        sig_process = inspect.signature(process_single_dna)
        self.assertIn("dna_sequence", sig_process.parameters)

        # Check run_batch signature
        sig_run = inspect.signature(run_batch)
        self.assertIn("correlation_id", sig_run.parameters)

    def test_log_structured_telemetry_hygiene(self):
        """Ensure log_structured emits valid JSON with correct ISO 8601 UTC timestamp format and all mandatory fields."""
        with patch("builtins.print") as mock_print:
            log_structured(
                correlation_id="test-corr-123",
                chain_name="test_chain",
                step="test_step",
                outcome="success",
                latency_ms=150,
                actor_id="test_actor",
                idempotency_key="test_key",
                outcome_detail="test detail"
            )

            mock_print.assert_called_once()
            log_line = mock_print.call_args[0][0]

            self.assertTrue(log_line.startswith("JSON_LOG: "))
            json_str = log_line[len("JSON_LOG: "):]

            # Must be valid JSON
            log_data = json.loads(json_str)

            # Check mandatory telemetry fields
            mandatory_fields = [
                "timestamp", "correlation_id", "actor_id", "chain_name",
                "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
            ]
            for field in mandatory_fields:
                self.assertIn(field, log_data)

            # Verify UTC ISO 8601 timestamp format with trailing Z
            timestamp = log_data["timestamp"]
            # Format: YYYY-MM-DDTHH:MM:SSZ
            self.assertTrue(timestamp.endswith("Z"), f"Timestamp '{timestamp}' does not end with Z indicating UTC timezone.")
            pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
            self.assertTrue(re.match(pattern, timestamp), f"Timestamp '{timestamp}' is not in correct ISO 8601 format.")

if __name__ == '__main__':
    unittest.main()
