import unittest
import inspect
import json
import io
import sys
import uuid
from utils.dna_calculator import DNACalculator, Rule
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
    def test_naming_alignment_dna_sequence(self):
        """Verify canonical naming: parse methods accept 'dna_sequence'."""
        calc_sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', calc_sig.parameters)

        rule_sig = inspect.signature(Rule.parse)
        self.assertIn('dna_sequence', rule_sig.parameters)

    def test_exception_taxonomy(self):
        """Verify exception taxonomy hierarchy under DNAProcessingError."""
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_dna_status_enum_values(self):
        """Verify explicit terminal states in DNAStatus string enum."""
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")
        self.assertEqual(DNAStatus.REFUSED, "refused")

    def test_structured_log_field_completeness(self):
        """Verify that log_structured emits required observability keys."""
        captured_output = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured_output

        correlation_id = str(uuid.uuid4())
        try:
            log_structured(
                correlation_id=correlation_id,
                chain_name="dna_batch_parser",
                step="test_step",
                outcome=DNAStatus.SUCCESS,
                latency_ms=12.34,
                actor_id="test_actor",
                idempotency_key="VOL08900750712",
                outcome_detail="test_detail"
            )
        finally:
            sys.stdout = old_stdout

        output_str = captured_output.getvalue().strip()
        self.assertTrue(output_str.startswith("JSON_LOG: "))

        json_part = output_str[len("JSON_LOG: "):]
        log_data = json.loads(json_part)

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
            self.assertIn(key, log_data)

        self.assertEqual(log_data["correlation_id"], correlation_id)
        self.assertEqual(log_data["chain_name"], "dna_batch_parser")
        self.assertEqual(log_data["step"], "test_step")
        self.assertEqual(log_data["outcome"], "success")
        self.assertEqual(log_data["actor_id"], "test_actor")
        self.assertEqual(log_data["idempotency_key"], "VOL08900750712")


if __name__ == '__main__':
    unittest.main()
