import unittest
import json
import inspect
from unittest.mock import patch
from utils.dna_ui import (
    run_batch,
    BatchResult,
    DNAStatus,
    log_structured,
    DNAProcessingError,
    RuleLoadError,
    InputReadError,
    PersistenceError,
    LedgerSaveError,
    AtomicWriteError
)

class TestMaintainability(unittest.TestCase):
    def test_naming_alignment_conventions(self):
        """Ensure canonical naming alignment is enforced in signatures."""
        sig = inspect.signature(run_batch)
        self.assertIn('correlation_id', sig.parameters, "run_batch signature must contain correlation_id")

    def test_exception_taxonomy(self):
        """Ensure clear, typed error hierarchy is defined and maintained."""
        self.assertTrue(issubclass(DNAProcessingError, Exception))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_result_dto_structure(self):
        """Ensure BatchResult carries standard fields."""
        res = BatchResult(status='SUCCESS', processed_count=3, total_ledger_items=5)
        self.assertEqual(res.status, 'SUCCESS')
        self.assertEqual(res.processed_count, 3)
        self.assertEqual(res.total_ledger_items, 5)

    def test_dna_status_enum(self):
        """Ensure DNAStatus uses standardized lowercase values for backward compatibility."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_structured_log_hygiene(self):
        """Ensure structured log fields are complete and follow the standard prefix format."""
        with patch('builtins.print') as mock_print:
            log_structured(
                correlation_id="test-corr-123",
                chain_name="test-chain",
                step="test-step",
                outcome="success",
                latency_ms=15,
                idempotency_key="seq-abc-123",
                outcome_detail="Everything was great",
                actor_id="test-actor"
            )
            mock_print.assert_called_once()
            printed_arg = mock_print.call_args[0][0]
            self.assertTrue(printed_arg.startswith("JSON_LOG: "))

            # Parse JSON and verify keys
            json_str = printed_arg[len("JSON_LOG: "):]
            log_data = json.loads(json_str)

            mandatory_keys = [
                "timestamp", "correlation_id", "actor_id", "chain_name",
                "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
            ]
            for key in mandatory_keys:
                self.assertIn(key, log_data, f"Structured log must contain the '{key}' key")

            self.assertEqual(log_data["correlation_id"], "test-corr-123")
            self.assertEqual(log_data["chain_name"], "test-chain")
            self.assertEqual(log_data["step"], "test-step")
            self.assertEqual(log_data["outcome"], "success")
            self.assertEqual(log_data["latency_ms"], 15)
            self.assertEqual(log_data["idempotency_key"], "seq-abc-123")
            self.assertEqual(log_data["outcome_detail"], "Everything was great")
            self.assertEqual(log_data["actor_id"], "test-actor")

if __name__ == '__main__':
    unittest.main()
