import io
import json
import unittest
from unittest.mock import patch
from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    PersistenceError,
    InputReadError,
    RuleLoadError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError,
    log_structured
)

class TestMaintainability(unittest.TestCase):
    def test_dna_status_enum_values(self):
        """Verify DNAStatus enum uses lowercase string values."""
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")
        self.assertEqual(DNAStatus.REFUSED, "refused")

    def test_exception_taxonomy(self):
        """Verify typed exception hierarchy."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_structured_log_fields(self):
        """Verify log_structured outputs JSON with all mandatory fields."""
        buf = io.StringIO()
        with patch('sys.stdout', buf):
            log_structured(
                correlation_id="test_cid_123",
                actor_id="test_actor",
                chain_name="dna_batch_parser",
                step="process_sequence",
                outcome=DNAStatus.SUCCESS,
                latency_ms=12.345,
                idempotency_key="VOL08900750712",
                outcome_detail="Parsed volume sequence"
            )

        output = buf.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "))

        json_str = output[len("JSON_LOG: "):]
        payload = json.loads(json_str)

        required_keys = {
            "timestamp",
            "correlation_id",
            "actor_id",
            "chain_name",
            "step",
            "outcome",
            "latency_ms",
            "idempotency_key",
            "outcome_detail"
        }
        self.assertTrue(required_keys.issubset(set(payload.keys())))
        self.assertEqual(payload["correlation_id"], "test_cid_123")
        self.assertEqual(payload["actor_id"], "test_actor")
        self.assertEqual(payload["chain_name"], "dna_batch_parser")
        self.assertEqual(payload["step"], "process_sequence")
        self.assertEqual(payload["outcome"], "success")
        self.assertEqual(payload["idempotency_key"], "VOL08900750712")

if __name__ == '__main__':
    unittest.main()
