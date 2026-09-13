import unittest
import json
import io
import contextlib
from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    RuleLoadError,
    InputReadError,
    PersistenceError,
    LedgerSaveError,
    AtomicWriteError,
    log_structured
)

class TestMaintainability(unittest.TestCase):
    def test_dna_status_values(self):
        """Verify DNAStatus enum string values match expectations."""
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")

    def test_exception_hierarchy(self):
        """Verify typed error inheritance hierarchy."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_structured_log_keys(self):
        """Verify log_structured emits expected fields in JSON output."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            log_structured(
                correlation_id="test-corr-id",
                chain_name="dna_batch_parsing",
                step="sequence_parsing",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=12.34,
                actor_id="test_actor",
                idempotency_key="VOL100",
                outcome_detail="Parsed successfully"
            )

        output = buf.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG:"))
        json_str = output[len("JSON_LOG:"):]
        payload = json.loads(json_str)

        required_keys = {
            "timestamp",
            "correlation_id",
            "chain_name",
            "step",
            "outcome",
            "latency_ms",
            "actor_id",
            "idempotency_key",
            "outcome_detail"
        }
        self.assertTrue(required_keys.issubset(payload.keys()))
        self.assertEqual(payload["correlation_id"], "test-corr-id")
        self.assertEqual(payload["chain_name"], "dna_batch_parsing")
        self.assertEqual(payload["outcome"], "success")

if __name__ == '__main__':
    unittest.main()
