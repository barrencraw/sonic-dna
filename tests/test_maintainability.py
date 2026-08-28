import unittest
import json
import io
from sys import stdout
from unittest.mock import patch

from utils.dna_ui import (
    DNAStatus,
    log_structured,
    DNAProcessingError,
    InputReadError,
    RuleLoadError,
    PersistenceError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError
)

class TestMaintainability(unittest.TestCase):
    def test_dna_status_enum_values(self):
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_exception_taxonomy_hierarchy(self):
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_structured_log_schema(self):
        buf = io.StringIO()
        with patch('sys.stdout', buf):
            log_structured(
                correlation_id="test-cid-123",
                actor_id="test_actor",
                chain_name="dna_batch_parse",
                step="test_step",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=42,
                idempotency_key="VOL100",
                outcome_detail="Test detail"
            )

        output = buf.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "))

        json_str = output[len("JSON_LOG: "):]
        log_data = json.loads(json_str)

        required_keys = [
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        ]
        for key in required_keys:
            self.assertIn(key, log_data)

        self.assertEqual(log_data["correlation_id"], "test-cid-123")
        self.assertEqual(log_data["actor_id"], "test_actor")
        self.assertEqual(log_data["chain_name"], "dna_batch_parse")
        self.assertEqual(log_data["step"], "test_step")
        self.assertEqual(log_data["outcome"], "success")
        self.assertEqual(log_data["latency_ms"], 42)
        self.assertEqual(log_data["idempotency_key"], "VOL100")
        self.assertEqual(log_data["outcome_detail"], "Test detail")

if __name__ == '__main__':
    unittest.main()
