import unittest
import io
import sys
import json
import inspect
from utils.dna_calculator import DNACalculator, Rule
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
    def test_naming_alignment_signatures(self):
        """Verify canonical parameter name 'dna_sequence' in DNACalculator.parse and Rule.parse."""
        calc_params = list(inspect.signature(DNACalculator.parse).parameters.keys())
        self.assertIn('dna_sequence', calc_params, "DNACalculator.parse must use parameter name 'dna_sequence'")

        rule_params = list(inspect.signature(Rule.parse).parameters.keys())
        self.assertIn('dna_sequence', rule_params, "Rule.parse must use parameter name 'dna_sequence'")

    def test_exception_taxonomy_hierarchy(self):
        """Verify typed error classifications subclass appropriate base errors."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_dna_status_enum_values(self):
        """Verify DNAStatus enum values are lowercase strings."""
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")
        self.assertEqual(DNAStatus.REFUSED, "refused")

    def test_structured_log_schema_and_formatting(self):
        """Verify log_structured outputs JSON_LOG: prefix with required schema keys."""
        captured_output = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = captured_output
            log_structured(
                step="test_step",
                outcome=DNAStatus.SUCCESS,
                latency_ms=12.34,
                correlation_id="test-corr-id",
                actor_id="test-actor",
                idempotency_key="VOL100",
                outcome_detail="All good"
            )
        finally:
            sys.stdout = old_stdout

        raw_log = captured_output.getvalue().strip()
        self.assertTrue(raw_log.startswith("JSON_LOG: "), f"Log output must start with 'JSON_LOG: ', got: {raw_log}")

        json_str = raw_log[len("JSON_LOG: "):]
        data = json.loads(json_str)

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
            self.assertIn(key, data, f"Structured log entry missing required key: {key}")

        self.assertEqual(data["correlation_id"], "test-corr-id")
        self.assertEqual(data["actor_id"], "test-actor")
        self.assertEqual(data["chain_name"], "dna_batch_parser")
        self.assertEqual(data["step"], "test_step")
        self.assertEqual(data["outcome"], "success")
        self.assertEqual(data["latency_ms"], 12.34)
        self.assertEqual(data["idempotency_key"], "VOL100")
        self.assertEqual(data["outcome_detail"], "All good")

if __name__ == "__main__":
    unittest.main()
