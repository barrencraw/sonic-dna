import unittest
import io
import json
import sys
from unittest.mock import patch
from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    InputReadError,
    RuleLoadError,
    PersistenceError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError,
    log_structured,
)
from utils.dna_calculator import RuleParseError

class TestMaintainability(unittest.TestCase):
    def test_dna_status_enum_values(self):
        """Ensure DNAStatus enum values match canonical lowercase strings."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_exception_taxonomy_hierarchy(self):
        """Ensure exception taxonomy maintains expected inheritance relationships."""
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_log_structured_schema(self):
        """Ensure log_structured emits JSON with exact required schema fields."""
        captured_output = io.StringIO()
        with patch('sys.stdout', captured_output):
            log_structured(
                correlation_id="test-corr-123",
                chain_name="dna_batch_parser",
                step="test_step",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=42,
                actor_id="unit_test_actor",
                idempotency_key="VOL100",
                outcome_detail="Parsed successfully"
            )

        log_output = captured_output.getvalue().strip()
        self.assertTrue(log_output.startswith("JSON_LOG: "))

        json_str = log_output[len("JSON_LOG: "):]
        log_data = json.loads(json_str)

        required_keys = [
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        ]
        for key in required_keys:
            self.assertIn(key, log_data)

        self.assertEqual(log_data["correlation_id"], "test-corr-123")
        self.assertEqual(log_data["actor_id"], "unit_test_actor")
        self.assertEqual(log_data["chain_name"], "dna_batch_parser")
        self.assertEqual(log_data["step"], "test_step")
        self.assertEqual(log_data["outcome"], "success")
        self.assertEqual(log_data["latency_ms"], 42)
        self.assertEqual(log_data["idempotency_key"], "VOL100")
        self.assertEqual(log_data["outcome_detail"], "Parsed successfully")

if __name__ == '__main__':
    unittest.main()
