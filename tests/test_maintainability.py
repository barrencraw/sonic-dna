import unittest
import inspect
import json
import io
import sys
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
    def test_dna_status_enum_values(self):
        """Verify DNAStatus enum uses exact canonical lowercase string values."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")
        self.assertIsInstance(DNAStatus.SUCCESS, str)

    def test_naming_alignment_dna_sequence(self):
        """Verify parse methods enforce canonical parameter name 'dna_sequence'."""
        rule_sig = inspect.signature(Rule.parse)
        calc_sig = inspect.signature(DNACalculator.parse)

        self.assertIn("dna_sequence", rule_sig.parameters)
        self.assertIn("dna_sequence", calc_sig.parameters)

    def test_exception_taxonomy_hierarchy(self):
        """Verify typed error classification hierarchy for batch processing."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))
        self.assertTrue(issubclass(LedgerLoadError, DNAProcessingError))
        self.assertTrue(issubclass(AtomicWriteError, DNAProcessingError))

    def test_structured_logging_schema(self):
        """Verify structured logging output format and mandatory field presence."""
        captured_output = io.StringIO()
        original_stdout = sys.stdout
        try:
            sys.stdout = captured_output
            log_structured(
                chain_name="dna_batch_parser",
                step="test_step",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=12,
                correlation_id="test-corr-id-123",
                actor_id="test_actor",
                idempotency_key="VOL000111222",
                outcome_detail="Test execution details"
            )
        finally:
            sys.stdout = original_stdout

        output_str = captured_output.getvalue().strip()
        self.assertTrue(output_str.startswith("JSON_LOG:"))

        json_str = output_str[len("JSON_LOG:"):]
        log_data = json.loads(json_str)

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
        self.assertEqual(set(log_data.keys()), required_keys)
        self.assertEqual(log_data["chain_name"], "dna_batch_parser")
        self.assertEqual(log_data["step"], "test_step")
        self.assertEqual(log_data["outcome"], "success")
        self.assertEqual(log_data["correlation_id"], "test-corr-id-123")
        self.assertEqual(log_data["actor_id"], "test_actor")
        self.assertEqual(log_data["idempotency_key"], "VOL000111222")

if __name__ == '__main__':
    unittest.main()
