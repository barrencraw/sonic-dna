import unittest
import inspect
import io
import json
from contextlib import redirect_stdout
from utils.dna_calculator import Rule, DNACalculator
from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    RuleLoadError,
    InputReadError,
    PersistenceError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError,
    log_structured,
)

class TestMaintainabilityAndSignal(unittest.TestCase):
    def test_dna_sequence_naming_alignment(self):
        """Verify parameter name 'dna_sequence' in Rule.parse and DNACalculator.parse."""
        rule_sig = inspect.signature(Rule.parse)
        calc_sig = inspect.signature(DNACalculator.parse)

        self.assertIn('dna_sequence', rule_sig.parameters, "Rule.parse must accept 'dna_sequence'")
        self.assertIn('dna_sequence', calc_sig.parameters, "DNACalculator.parse must accept 'dna_sequence'")

    def test_dna_status_enum_values(self):
        """Verify explicit terminal state values in DNAStatus enum."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_error_taxonomy_inheritance(self):
        """Verify typed error inheritance under DNAProcessingError and PersistenceError."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_log_structured_schema(self):
        """Verify structured JSON log output format and required keys."""
        f = io.StringIO()
        with redirect_stdout(f):
            log_structured(
                correlation_id="test-corr-123",
                actor_id="test-actor",
                chain_name="test-chain",
                step="test_step",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=15,
                idempotency_key="VOL08900750712",
                outcome_detail="Rule parsed: Volume"
            )

        out = f.getvalue().strip()
        self.assertTrue(out.startswith("JSON_LOG:"))

        json_str = out[len("JSON_LOG:"):]
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
            self.assertIn(key, data, f"Structured log missing key: {key}")

        self.assertEqual(data["correlation_id"], "test-corr-123")
        self.assertEqual(data["actor_id"], "test-actor")
        self.assertEqual(data["chain_name"], "test-chain")
        self.assertEqual(data["step"], "test_step")
        self.assertEqual(data["outcome"], "success")

if __name__ == '__main__':
    unittest.main()
