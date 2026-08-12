import unittest
import inspect
import json
import re
import datetime
import io
import os
from unittest.mock import patch

from utils.dna_ui import (
    run_batch,
    DNAProcessingError,
    PersistenceError,
    InputReadError,
    LedgerSaveError,
    LedgerLoadError,
    AtomicWriteError,
    DNAStatus,
    BatchResult,
    log_structured
)

class TestMaintainability(unittest.TestCase):
    def test_run_batch_signature(self):
        """Verify that run_batch has correlation_id as a parameter in its signature."""
        sig = inspect.signature(run_batch)
        self.assertIn('correlation_id', sig.parameters, "run_batch must accept a correlation_id parameter.")
        # Ensure it has a default of None
        self.assertIsNone(sig.parameters['correlation_id'].default, "correlation_id parameter should default to None.")

    def test_exception_taxonomy(self):
        """Validate the exception hierarchy for typed error classification."""
        # InputReadError subclassing DNAProcessingError
        self.assertTrue(issubclass(InputReadError, DNAProcessingError), "InputReadError must inherit from DNAProcessingError")
        # LedgerSaveError subclassing PersistenceError
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError), "LedgerSaveError must inherit from PersistenceError")
        # LedgerLoadError subclassing PersistenceError
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError), "LedgerLoadError must inherit from PersistenceError")
        # AtomicWriteError subclassing PersistenceError
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError), "AtomicWriteError must inherit from PersistenceError")
        # PersistenceError subclassing DNAProcessingError
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError), "PersistenceError must inherit from DNAProcessingError")

    def test_load_ledger_raises_ledger_load_error_on_corrupt_json(self):
        """Verify load_ledger raises LedgerLoadError when ledger file has corrupted JSON."""
        import tempfile
        from utils.dna_ui import load_ledger

        with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp:
            tmp.write("not-valid-json")
            tmp_path = tmp.name

        try:
            with self.assertRaises(LedgerLoadError):
                load_ledger(tmp_path)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    @patch('sys.stdout', new_callable=io.StringIO)
    def test_log_structured_fields_and_format(self, mock_stdout):
        """Verify that log_structured emits prefixed JSON with all mandatory fields and valid ISO 8601 UTC timestamps."""
        correlation_id = "test-corr-id-123"
        step = "test_step"
        outcome = "success"
        latency_ms = 45
        actor_id = "test_actor"
        idempotency_key = "test_key"
        outcome_detail = "test_detail"

        log_structured(
            correlation_id=correlation_id,
            step=step,
            outcome=outcome,
            latency_ms=latency_ms,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            outcome_detail=outcome_detail
        )

        output = mock_stdout.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG:"), "Log output must start with 'JSON_LOG:' prefix")

        # Strip the prefix and parse JSON
        json_str = output[len("JSON_LOG:"):]
        log_data = json.loads(json_str)

        # Mandatory fields assertion
        mandatory_fields = [
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        ]
        for field in mandatory_fields:
            self.assertIn(field, log_data, f"Structured log is missing mandatory field: {field}")

        # Assert correct field values
        self.assertEqual(log_data["correlation_id"], correlation_id)
        self.assertEqual(log_data["step"], step)
        self.assertEqual(log_data["outcome"], outcome)
        self.assertEqual(log_data["latency_ms"], latency_ms)
        self.assertEqual(log_data["actor_id"], actor_id)
        self.assertEqual(log_data["idempotency_key"], idempotency_key)
        self.assertEqual(log_data["outcome_detail"], outcome_detail)

        # ISO 8601 UTC format check
        timestamp = log_data["timestamp"]
        self.assertTrue(timestamp.endswith("Z"), "Timestamp must end with 'Z' indicating UTC time")

        # Verify it can be parsed as a valid ISO datetime
        try:
            # datetime.fromisoformat supports Z in Python 3.11+
            # Replacing Z with +00:00 is compatible across Python versions
            parsed_dt = datetime.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            self.assertIsNotNone(parsed_dt)
        except ValueError as e:
            self.fail(f"Timestamp '{timestamp}' is not a valid ISO 8601 format: {e}")

if __name__ == '__main__':
    unittest.main()
