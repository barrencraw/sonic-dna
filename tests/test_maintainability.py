import unittest
import inspect
import json
import io
from contextlib import redirect_stdout
from utils.dna_calculator import Rule, DNACalculator
from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    InputReadError,
    RuleLoadError,
    PersistenceError,
    LedgerSaveError,
    AtomicWriteError,
    log_structured,
    run_batch
)

class TestMaintainabilityAndSignal(unittest.TestCase):
    """
    Regression guard for:
    1. Naming alignment (canonical parameter 'dna_sequence').
    2. Explicit terminal states and typed error hierarchy.
    3. Structured log schema hygiene and field presence.
    """

    def test_naming_alignment_rule_parse_signature(self):
        """Ensure Rule.parse has 'dna_sequence' in its parameter signature."""
        sig = inspect.signature(Rule.parse)
        self.assertIn('dna_sequence', sig.parameters,
                      "Rule.parse must have parameter 'dna_sequence' to maintain naming alignment")

    def test_naming_alignment_calculator_parse_signature(self):
        """Ensure DNACalculator.parse has 'dna_sequence' in its parameter signature."""
        sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', sig.parameters,
                      "DNACalculator.parse must have parameter 'dna_sequence' to maintain naming alignment")

    def test_error_taxonomy_inheritance(self):
        """Verify typed error hierarchy under DNAProcessingError."""
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_terminal_status_enum(self):
        """Ensure explicit terminal statuses exist and match expected values."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")

    def test_structured_logging_schema(self):
        """Ensure log_structured emits all required standard fields."""
        f = io.StringIO()
        with redirect_stdout(f):
            log_structured(
                step="test_step",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=12.34,
                idempotency_key="VOL123",
                correlation_id="corr-999"
            )
        output = f.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG:"))

        payload = json.loads(output[len("JSON_LOG:"):])
        required_fields = [
            "correlation_id",
            "chain_name",
            "step",
            "outcome",
            "latency_ms",
            "actor_id",
            "idempotency_key"
        ]
        for field in required_fields:
            self.assertIn(field, payload, f"Missing required log field: {field}")

        self.assertEqual(payload["chain_name"], "dna_batch_parser")
        self.assertEqual(payload["step"], "test_step")
        self.assertEqual(payload["outcome"], "success")
        self.assertEqual(payload["latency_ms"], 12.34)
        self.assertEqual(payload["actor_id"], "batch_parser")
        self.assertEqual(payload["idempotency_key"], "VOL123")
        self.assertEqual(payload["correlation_id"], "corr-999")

if __name__ == '__main__':
    unittest.main()
