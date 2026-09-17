import unittest
import os
import json
import io
import contextlib
import inspect
from utils.dna_calculator import DNACalculator, Rule
from utils.dna_ui import (
    run_batch,
    DNAStatus,
    DNAProcessingError,
    RuleLoadError,
    InputReadError,
    PersistenceError,
    AtomicWriteError,
    LedgerSaveError
)

class TestMaintainability(unittest.TestCase):
    def test_naming_alignment_dna_sequence(self):
        """Verify that parse methods across DNACalculator and Rule accept `dna_sequence`."""
        calc_sig = inspect.signature(DNACalculator.parse)
        self.assertIn("dna_sequence", calc_sig.parameters)

        rule_sig = inspect.signature(Rule.parse)
        self.assertIn("dna_sequence", rule_sig.parameters)

    def test_dnastatus_lowercase_values(self):
        """Verify that DNAStatus enum maintains expected canonical string values."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")

    def test_structured_logging_keys(self):
        """Verify that structured logging output contains required observability fields."""
        stdout_capture = io.StringIO()
        with contextlib.redirect_stdout(stdout_capture):
            run_batch(correlation_id="test-corr-123")

        output = stdout_capture.getvalue()
        lines = [line for line in output.splitlines() if line.startswith("JSON_LOG:")]
        self.assertGreater(len(lines), 0, "Expected at least one JSON log line")

        for line in lines:
            json_str = line.replace("JSON_LOG:", "").strip()
            payload = json.loads(json_str)
            required_keys = [
                "timestamp", "correlation_id", "actor_id", "chain_name",
                "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
            ]
            for key in required_keys:
                self.assertIn(key, payload)

            self.assertEqual(payload["correlation_id"], "test-corr-123")

    def test_typed_exception_hierarchy(self):
        """Verify exception taxonomy subclasses DNAProcessingError."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))

if __name__ == '__main__':
    unittest.main()
