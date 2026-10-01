import unittest
import os
import json
import io
import contextlib
from utils.dna_calculator import DNACalculator, Rule
from utils.dna_ui import DNAStatus, log_structured, DNAProcessingError, PersistenceError, InputReadError, LedgerLoadError, LedgerSaveError, AtomicWriteError

class TestMaintainability(unittest.TestCase):
    def test_dna_calculator_naming_alignment(self):
        """Verify that DNACalculator and Rule parse methods accept 'dna_sequence' keyword argument."""
        calculator = DNACalculator(rules_folder='rules')
        rule = calculator.rules['VOL']

        # Test Rule.parse with dna_sequence kwarg
        values = rule.parse(dna_sequence="VOL08900750712")
        self.assertIsInstance(values, dict)

        # Test DNACalculator.parse with dna_sequence kwarg
        res = calculator.parse(dna_sequence="VOL08900750712")
        self.assertEqual(res['rule'], 'Volume')

    def test_dna_status_enum_values(self):
        """Verify DNAStatus enum string values match terminal state contracts."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    test_dna_status_values = test_dna_status_enum_values

    def test_exception_taxonomy_hierarchy(self):
        """Verify typed exception taxonomy inheritance."""
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_structured_logging_format(self):
        """Verify that log_structured emits compliant JSON_LOG entries."""
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            log_structured(
                chain_name="test_chain",
                step="test_step",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=12.34,
                correlation_id="test-corr-id",
                actor_id="test-actor",
                idempotency_key="VOL123",
                outcome_detail="Detailed outcome"
            )

        output = stdout.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG:"))
        json_str = output[len("JSON_LOG:"):]
        data = json.loads(json_str)

        required_keys = {
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        }
        self.assertTrue(required_keys.issubset(data.keys()))
        self.assertEqual(data["correlation_id"], "test-corr-id")
        self.assertEqual(data["actor_id"], "test-actor")
        self.assertEqual(data["chain_name"], "test_chain")
        self.assertEqual(data["step"], "test_step")
        self.assertEqual(data["outcome"], "success")
        self.assertEqual(data["latency_ms"], 12.34)
        self.assertEqual(data["idempotency_key"], "VOL123")
        self.assertEqual(data["outcome_detail"], "Detailed outcome")

if __name__ == '__main__':
    unittest.main()
