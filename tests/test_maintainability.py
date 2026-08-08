import unittest
import os
import json
import io
import sys
import datetime
from unittest.mock import patch, MagicMock

# Mock GUI dependencies
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

from utils.dna_ui import log_structured, run_batch, DNAStatus

class TestMaintainability(unittest.TestCase):
    def test_log_structured_format(self):
        """Verify log_structured outputs valid JSON with prefix and all mandatory fields."""
        captured_output = io.StringIO()
        sys.stdout = captured_output
        try:
            log_structured(
                step="test_step",
                outcome="success",
                correlation_id="test-corr-123",
                actor_id="test-actor",
                chain_name="test-chain",
                latency_ms=120,
                idempotency_key="test-key",
                outcome_detail="test detail"
            )
        finally:
            sys.stdout = sys.__stdout__

        output_str = captured_output.getvalue().strip()
        self.assertTrue(output_str.startswith("JSON_LOG: "))

        json_str = output_str[len("JSON_LOG: "):]
        log_data = json.loads(json_str)

        # Check mandatory fields
        mandatory_fields = [
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        ]
        for field in mandatory_fields:
            self.assertIn(field, log_data)

        self.assertEqual(log_data["correlation_id"], "test-corr-123")
        self.assertEqual(log_data["actor_id"], "test-actor")
        self.assertEqual(log_data["chain_name"], "test-chain")
        self.assertEqual(log_data["step"], "test_step")
        self.assertEqual(log_data["outcome"], "success")
        self.assertEqual(log_data["latency_ms"], 120)
        self.assertEqual(log_data["idempotency_key"], "test-key")
        self.assertEqual(log_data["outcome_detail"], "test detail")

        # Check ISO 8601 formatting of timestamp
        timestamp = log_data["timestamp"]
        self.assertTrue(timestamp.endswith("Z"), "Timestamp must end with 'Z'")
        # Parse it to verify validity
        dt = datetime.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        self.assertIsNotNone(dt)

    def test_dna_status_enum(self):
        """Verify DNAStatus enum lowercase values."""
        self.assertEqual(DNAStatus.SUCCESS, 'success')
        self.assertEqual(DNAStatus.ERROR, 'error')
        self.assertEqual(DNAStatus.SKIPPED, 'skipped')
        self.assertEqual(DNAStatus.REFUSED, 'refused')
