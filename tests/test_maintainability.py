import unittest
import inspect
import json
import re
import io
from unittest.mock import patch

from utils.dna_ui import (
    run_batch,
    BatchResult,
    DNAProcessingError,
    InputReadError,
    RuleLoadError,
    PersistenceError,
    LedgerSaveError,
    AtomicWriteError,
    log_structured
)

class TestMaintainability(unittest.TestCase):
    def test_run_batch_signature(self):
        """Ensure run_batch has correlation_id in its signature to prevent backsliding."""
        sig = inspect.signature(run_batch)
        self.assertIn('correlation_id', sig.parameters, "run_batch must accept correlation_id")

    def test_error_taxonomy(self):
        """Verify the typed error classification hierarchy."""
        self.assertTrue(issubclass(DNAProcessingError, Exception))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_batch_result_contract(self):
        """Ensure BatchResult has the required contract attributes."""
        # Instantiate a dummy result
        res = BatchResult(status="SUCCESS", processed_count=5, total_ledger_items=10)
        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(res.processed_count, 5)
        self.assertEqual(res.total_ledger_items, 10)

    def test_log_structured_hygiene(self):
        """Verify that structured logs contain all mandatory telemetry fields and follow formats."""
        with patch('sys.stdout', new_callable=io.StringIO) as mock_stdout:
            log_structured(
                step="test_step",
                outcome="success",
                latency_ms=123,
                correlation_id="test-corr-id",
                actor_id="test-actor",
                chain_name="test-chain",
                idempotency_key="test-key",
                outcome_detail="test detail"
            )
            output = mock_stdout.getvalue().strip()

            # Must start with JSON_LOG:
            prefix = "JSON_LOG: "
            self.assertTrue(output.startswith(prefix))

            # Parse the JSON part
            json_part = output[len(prefix):]
            log_data = json.loads(json_part)

            # Check mandatory fields
            mandatory_fields = [
                "timestamp", "correlation_id", "actor_id", "chain_name",
                "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
            ]
            for field in mandatory_fields:
                self.assertIn(field, log_data, f"Mandatory field {field} missing from structured log")

            # Verify ISO 8601 UTC timestamp format (e.g. YYYY-MM-DDTHH:MM:SSZ)
            timestamp = log_data["timestamp"]
            self.assertTrue(timestamp.endswith("Z"), "Timestamp must end with Z to designate UTC")

            # Match ISO format pattern: YYYY-MM-DDTHH:MM:SSZ
            pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
            self.assertTrue(re.match(pattern, timestamp), f"Timestamp {timestamp} does not match ISO 8601 format")

if __name__ == '__main__':
    unittest.main()
