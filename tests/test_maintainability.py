import unittest
import sys
import io
import json
from enum import Enum
from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    PersistenceError,
    InputReadError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError,
    log_structured
)

class TestMaintainability(unittest.TestCase):
    def test_dna_status_enum(self):
        """Verify DNAStatus enum uses standard lowercase values."""
        self.assertEqual(DNAStatus.SUCCESS, 'success')
        self.assertEqual(DNAStatus.ERROR, 'error')
        self.assertEqual(DNAStatus.SKIPPED, 'skipped')
        self.assertEqual(DNAStatus.REFUSED, 'refused')

    def test_exception_taxonomy(self):
        """Verify the exception class hierarchy."""
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))

    def test_log_structured_keys(self):
        """Verify standard structured log fields are present in emitted logs."""
        captured_output = io.StringIO()
        sys.stdout = captured_output
        try:
            log_structured(
                step="test_step",
                outcome=DNAStatus.SUCCESS,
                correlation_id="test-corr-123",
                actor_id="test_actor",
                chain_name="test_chain",
                latency_ms=12.34,
                idempotency_key="test_key",
                outcome_detail="test detail"
            )
        finally:
            sys.stdout = sys.__stdout__

        output_str = captured_output.getvalue().strip()
        self.assertTrue(output_str.startswith("JSON_LOG:"))
        json_part = output_str[len("JSON_LOG:"):].strip()
        log_data = json.loads(json_part)

        required_keys = [
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        ]
        for key in required_keys:
            self.assertIn(key, log_data)

        self.assertEqual(log_data["correlation_id"], "test-corr-123")
        self.assertEqual(log_data["actor_id"], "test_actor")
        self.assertEqual(log_data["chain_name"], "test_chain")
        self.assertEqual(log_data["step"], "test_step")
        self.assertEqual(log_data["outcome"], "success")
        self.assertEqual(log_data["latency_ms"], 12.34)
        self.assertEqual(log_data["idempotency_key"], "test_key")
        self.assertEqual(log_data["outcome_detail"], "test detail")

if __name__ == '__main__':
    unittest.main()
