import unittest
import io
import json
import inspect
from contextlib import redirect_stdout
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

    def test_naming_alignment_dna_sequence(self):
        """Verify that DNACalculator.parse and Rule.parse use 'dna_sequence' as parameter name."""
        rule_sig = inspect.signature(Rule.parse)
        calc_sig = inspect.signature(DNACalculator.parse)

        self.assertIn('dna_sequence', rule_sig.parameters, "Rule.parse must accept 'dna_sequence'")
        self.assertIn('dna_sequence', calc_sig.parameters, "DNACalculator.parse must accept 'dna_sequence'")

    def test_exception_taxonomy_and_enum_status(self):
        """Verify typed error inheritance and lowercase DNAStatus string values."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_structured_log_field_completeness(self):
        """Verify that log_structured outputs JSON with all required observability fields."""
        f = io.StringIO()
        with redirect_stdout(f):
            log_structured(
                correlation_id="test-corr-id",
                actor_id="test-actor",
                chain_name="test_chain",
                step="test_step",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=12,
                idempotency_key="V100",
                outcome_detail="detail_msg"
            )

        output = f.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "))

        raw_json = output.replace("JSON_LOG: ", "")
        log_obj = json.loads(raw_json)

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
            self.assertIn(key, log_obj, f"Structured log missing mandatory field '{key}'")

        self.assertEqual(log_obj["correlation_id"], "test-corr-id")
        self.assertEqual(log_obj["actor_id"], "test-actor")
        self.assertEqual(log_obj["chain_name"], "test_chain")
        self.assertEqual(log_obj["step"], "test_step")
        self.assertEqual(log_obj["outcome"], "success")
        self.assertEqual(log_obj["latency_ms"], 12)
        self.assertEqual(log_obj["idempotency_key"], "V100")
        self.assertEqual(log_obj["outcome_detail"], "detail_msg")


if __name__ == '__main__':
    unittest.main()
