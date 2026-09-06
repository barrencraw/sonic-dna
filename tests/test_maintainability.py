import unittest
import os
import json
import io
import contextlib
import sys
import utils.dna_calculator as dna_calc
from utils.dna_ui import (
    run_batch,
    DNAStatus,
    DNAProcessingError,
    RuleLoadError,
    InputReadError,
    PersistenceError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError
)

class TestMaintainabilityAndSignal(unittest.TestCase):
    def test_dna_status_enum_values(self):
        """Ensure DNAStatus enum values are canonical lowercase string literals."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_exception_taxonomy_hierarchy(self):
        """Ensure exception taxonomy inherits correctly from base classes."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))

    def test_canonical_naming_in_calculator_signature(self):
        """Ensure DNACalculator and Rule parse method parameters use 'dna_sequence'."""
        import inspect
        calc_sig = inspect.signature(dna_calc.DNACalculator.parse)
        rule_sig = inspect.signature(dna_calc.Rule.parse)

        self.assertIn("dna_sequence", calc_sig.parameters)
        self.assertIn("dna_sequence", rule_sig.parameters)

    def test_structured_log_schema_fields(self):
        """Verify structured log output contains all required observability fields."""
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            run_batch(correlation_id="test-corr-123", actor_id="test_actor")

        output = f.getvalue()
        log_lines = [line for line in output.splitlines() if line.startswith("JSON_LOG:")]
        self.assertGreater(len(log_lines), 0, "Structured log entries with JSON_LOG: prefix should be emitted.")

        required_keys = {
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        }

        for line in log_lines:
            json_str = line.replace("JSON_LOG:", "").strip()
            payload = json.loads(json_str)
            for k in required_keys:
                self.assertIn(k, payload, f"Missing required key '{k}' in structured log payload")

            self.assertEqual(payload["correlation_id"], "test-corr-123")
            self.assertEqual(payload["actor_id"], "test_actor")
            self.assertEqual(payload["chain_name"], "dna_batch_parser")

if __name__ == "__main__":
    unittest.main()
