import os
import sys
from unittest.mock import MagicMock

# Mock GUI/audio dependencies to keep tests fast and prevent window popups
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
import io
import contextlib
import datetime
from utils.dna_ui import run_batch, log_structured, DNAStatus, BatchResult

class TestMaintainability(unittest.TestCase):
    def test_run_batch_signature(self):
        """Verify that run_batch function signature contains the correlation_id parameter."""
        sig = inspect.signature(run_batch)
        self.assertIn('correlation_id', sig.parameters)
        # Check that it has a default of None
        self.assertIsNone(sig.parameters['correlation_id'].default)

    def test_log_structured_output_and_fields(self):
        """Verify that log_structured utility outputs valid structured logs with mandatory fields."""
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            log_structured(
                step="test_step",
                outcome=DNAStatus.SUCCESS,
                latency_ms=42,
                idempotency_key="VOL123",
                outcome_detail="Everything is good",
                correlation_id="corr-999",
                actor_id="user-1"
            )
        output = f.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG:"))

        # Parse the JSON part
        json_part = output[len("JSON_LOG:"):]
        log_data = json.loads(json_part)

        # Verify mandatory fields
        mandatory_fields = [
            "timestamp",
            "correlation_id",
            "actor_id",
            "chain_name",
            "step",
            "outcome",
            "latency_ms",
            "idempotency_key",
            "outcome_detail"
        ]
        for field in mandatory_fields:
            self.assertIn(field, log_data)

        # Verify specific values
        self.assertEqual(log_data["correlation_id"], "corr-999")
        self.assertEqual(log_data["actor_id"], "user-1")
        self.assertEqual(log_data["chain_name"], "dna_batch_parsing")
        self.assertEqual(log_data["step"], "test_step")
        self.assertEqual(log_data["outcome"], "success")
        self.assertEqual(log_data["latency_ms"], 42)
        self.assertEqual(log_data["idempotency_key"], "VOL123")
        self.assertEqual(log_data["outcome_detail"], "Everything is good")

        # Verify ISO 8601 UTC format: YYYY-MM-DDTHH:MM:SSZ
        timestamp_str = log_data["timestamp"]
        self.assertTrue(timestamp_str.endswith("Z"))
        try:
            datetime.datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            self.fail(f"Timestamp {timestamp_str} is not in %Y-%m-%dT%H:%M:%SZ format")

    def test_dna_status_lowercase_enums(self):
        """Verify that DNAStatus uses lowercase string values."""
        self.assertEqual(DNAStatus.SUCCESS, 'success')
        self.assertEqual(DNAStatus.ERROR, 'error')
        self.assertEqual(DNAStatus.SKIPPED, 'skipped')
        self.assertEqual(DNAStatus.REFUSED, 'refused')

    def test_batch_result_properties(self):
        """Verify that BatchResult is correctly structured."""
        res = BatchResult("SUCCESS", 5, 20)
        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(res.processed_count, 5)
        self.assertEqual(res.total_ledger_items, 20)
        self.assertIn("SUCCESS", repr(res))

if __name__ == '__main__':
    unittest.main()
