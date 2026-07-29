import unittest
import os
import json
import inspect
import datetime
import io
import sys
from unittest.mock import patch, MagicMock

# Mock GUI dependencies to prevent ModuleNotFoundError
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

from utils.dna_ui import run_batch, DNAStatus, log_structured, get_utc_timestamp

class TestMaintainability(unittest.TestCase):
    def test_run_batch_signature(self):
        """Verify that run_batch has correlation_id and actor_id in its signature."""
        sig = inspect.signature(run_batch)
        self.assertIn('correlation_id', sig.parameters)
        self.assertIn('actor_id', sig.parameters)

        # Verify default values
        self.assertIsNone(sig.parameters['correlation_id'].default)
        self.assertEqual(sig.parameters['actor_id'].default, 'system')

    def test_naming_conventions(self):
        """Verify that canonical name 'dna_sequence' is used in signatures and code."""
        # Let's inspect some of the helper function signatures in dna_ui
        from utils import dna_ui
        with open(dna_ui.__file__, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('dna_sequence_list', content)
        self.assertIn('dna_sequence', content)
        self.assertNotIn('dna_str', content) # Ensure deprecated 'dna_str' has been removed/renamed

    def test_log_structured_keys_and_timestamp(self):
        """Verify that log_structured emits valid JSON with precise keys and timestamp format."""
        captured_output = io.StringIO()
        with patch('sys.stdout', new=captured_output):
            log_structured(
                correlation_id="test-corr-id",
                actor_id="test-actor-id",
                chain_name="test-chain",
                step="test-step",
                outcome=DNAStatus.SUCCESS,
                latency_ms=42,
                idempotency_key="test-key",
                outcome_detail="test detail"
            )

        output = captured_output.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG:"))

        json_str = output.replace("JSON_LOG:", "", 1)
        log_data = json.loads(json_str)

        # Check mandatory keys
        mandatory_keys = [
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        ]
        for key in mandatory_keys:
            self.assertIn(key, log_data)

        # Check values and types
        self.assertEqual(log_data["correlation_id"], "test-corr-id")
        self.assertEqual(log_data["actor_id"], "test-actor-id")
        self.assertEqual(log_data["chain_name"], "test-chain")
        self.assertEqual(log_data["step"], "test-step")
        self.assertEqual(log_data["outcome"], "success")
        self.assertEqual(log_data["latency_ms"], 42)
        self.assertEqual(log_data["idempotency_key"], "test-key")
        self.assertEqual(log_data["outcome_detail"], "test detail")

        # Check precise ISO 8601 UTC timestamp format %Y-%m-%dT%H:%M:%SZ
        timestamp_str = log_data["timestamp"]
        try:
            parsed_dt = datetime.datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            self.fail(f"Timestamp '{timestamp_str}' does not match precise UTC ISO 8601 format %Y-%m-%dT%H:%M:%SZ")

    def test_dna_status_enum_values(self):
        """Verify that DNAStatus contains only lower-case canonical status values."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

if __name__ == '__main__':
    unittest.main()
