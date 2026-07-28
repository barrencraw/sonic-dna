import sys
import unittest
import inspect
import json
import datetime
from unittest.mock import patch, MagicMock

# Mock GUI dependencies to prevent ModuleNotFoundError on headless run
sys.modules["PySide6"] = MagicMock()
sys.modules["PySide6.QtWidgets"] = MagicMock()
sys.modules["PySide6.QtCore"] = MagicMock()
sys.modules["PySide6.QtGui"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

from utils.dna_ui import run_batch, log_structured, DNAStatus

class TestMaintainability(unittest.TestCase):
    def test_run_batch_signature(self):
        """Verify the core batch processing signature contains 'correlation_id'."""
        sig = inspect.signature(run_batch)
        self.assertIn('correlation_id', sig.parameters, "run_batch must accept correlation_id")

    def test_dna_status_lowercase(self):
        """Verify DNAStatus uses lowercase values for legacy/existing test compatibility."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    @patch('builtins.print')
    def test_log_structured_fields(self, mock_print):
        """Verify log_structured emits prefix 'JSON_LOG:' and has all mandatory telemetry fields."""
        log_structured(
            correlation_id="test-corr-id",
            actor_id="test-actor-id",
            chain_name="test-chain",
            step="test-step",
            outcome=DNAStatus.SUCCESS,
            latency_ms=123,
            idempotency_key="test-key",
            outcome_detail="test detail"
        )

        mock_print.assert_called_once()
        print_arg = mock_print.call_args[0][0]
        self.assertTrue(print_arg.startswith("JSON_LOG: "))

        json_str = print_arg.replace("JSON_LOG: ", "", 1)
        log_data = json.loads(json_str)

        # Verify mandatory keys
        mandatory_keys = [
            'timestamp', 'correlation_id', 'actor_id', 'chain_name',
            'step', 'outcome', 'latency_ms', 'idempotency_key', 'outcome_detail'
        ]
        for key in mandatory_keys:
            self.assertIn(key, log_data)

        # Verify timestamp is ISO 8601 UTC
        timestamp_str = log_data['timestamp']
        try:
            # Parse precisely using strptime to ensure it ends with Z and matches %Y-%m-%dT%H:%M:%SZ
            datetime.datetime.strptime(timestamp_str, '%Y-%m-%dT%H:%M:%SZ')
        except ValueError:
            self.fail("Timestamp is not in precise UTC ISO 8601 format %Y-%m-%dT%H:%M:%SZ")

if __name__ == '__main__':
    unittest.main()
