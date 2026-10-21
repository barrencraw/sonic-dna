import unittest
import json
import io
import contextlib
from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    InputReadError,
    RuleLoadError,
    PersistenceError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError,
    log_structured
)

class TestMaintainability(unittest.TestCase):
    def test_dna_status_enum_values(self):
        """Verify explicit terminal states use string lowercase canonical values."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_structured_log_fields(self):
        """Verify structured logging outputs valid JSON with mandatory fields."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            log_structured({
                "correlation_id": "test-uuid-1234",
                "actor_id": "test_agent",
                "chain_name": "dna_batch_parser",
                "step": "process_sequence",
                "outcome": DNAStatus.SUCCESS.value,
                "latency_ms": 42,
                "idempotency_key": "VOL08900750712",
                "outcome_detail": "Successfully parsed"
            })

        output = buf.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG:"))
        json_str = output[len("JSON_LOG:"):]
        log_dict = json.loads(json_str)

        required_keys = [
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
        for key in required_keys:
            self.assertIn(key, log_dict, f"Missing required log key: {key}")

        self.assertEqual(log_dict["correlation_id"], "test-uuid-1234")
        self.assertEqual(log_dict["actor_id"], "test_agent")
        self.assertEqual(log_dict["chain_name"], "dna_batch_parser")
        self.assertEqual(log_dict["step"], "process_sequence")
        self.assertEqual(log_dict["outcome"], "success")

    def test_exception_taxonomy_hierarchy(self):
        """Verify typed error taxonomy inheritance."""
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))


if __name__ == '__main__':
    unittest.main()
