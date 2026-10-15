import unittest
import inspect
import json
import io
import contextlib
from utils.dna_calculator import DNACalculator
from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    RuleLoadError,
    InputReadError,
    PersistenceError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError,
    log_structured
)

class TestMaintainability(unittest.TestCase):

    def test_naming_alignment_calculator_signature(self):
        """Verify DNACalculator.parse parameter is named dna_sequence."""
        sig = inspect.signature(DNACalculator.parse)
        params = list(sig.parameters.keys())
        self.assertIn("dna_sequence", params, "DNACalculator.parse must use parameter 'dna_sequence'")

    def test_dna_status_enum_values(self):
        """Verify DNAStatus enum uses lowercase string values."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")
        # Direct string comparison compatibility
        self.assertEqual(DNAStatus.SUCCESS, "success")

    def test_exception_taxonomy(self):
        """Verify exception hierarchy inheritance."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_structured_log_format(self):
        """Verify structured log emitted contains all mandatory schema keys."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            log_structured(
                correlation_id="test-corr-123",
                chain_name="dna_batch_processing",
                step="parse_sequence",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=12.34,
                actor_id="test_actor",
                idempotency_key="VOL123",
                outcome_detail="Parsed successfully"
            )

        output = buf.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG:"))
        json_part = output[len("JSON_LOG:"):]
        data = json.loads(json_part)

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
            self.assertIn(key, data, f"Structured log entry missing key '{key}'")

        self.assertEqual(data["correlation_id"], "test-corr-123")
        self.assertEqual(data["chain_name"], "dna_batch_processing")
        self.assertEqual(data["step"], "parse_sequence")
        self.assertEqual(data["outcome"], "success")
        self.assertEqual(data["actor_id"], "test_actor")
        self.assertEqual(data["idempotency_key"], "VOL123")
        self.assertEqual(data["outcome_detail"], "Parsed successfully")

if __name__ == '__main__':
    unittest.main()
