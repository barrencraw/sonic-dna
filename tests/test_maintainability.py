import unittest
import inspect
import json
import io
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
        """Guard against naming backsliding: ensure parse signature parameters use canonical name dna_sequence."""
        calc_sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', calc_sig.parameters, "DNACalculator.parse must use parameter name 'dna_sequence'")

        rule_sig = inspect.signature(Rule.parse)
        self.assertIn('dna_sequence', rule_sig.parameters, "Rule.parse must use parameter name 'dna_sequence'")

    def test_typed_exception_hierarchy(self):
        """Guard against exception classification regressions."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_explicit_terminal_states(self):
        """Guard against status string regressions."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")

    def test_structured_log_fields(self):
        """Guard against log field regressions in observability telemetry."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            log_structured(
                chain_name="test_chain",
                step="test_step",
                outcome=DNAStatus.SUCCESS,
                latency_ms=12.34,
                correlation_id="test-corr-id-123",
                actor_id="test_actor",
                idempotency_key="V100",
                outcome_detail="Test detail"
            )

        output = buf.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "))
        json_str = output[len("JSON_LOG: "):]
        log_data = json.loads(json_str)

        required_keys = [
            'timestamp',
            'correlation_id',
            'chain_name',
            'step',
            'outcome',
            'latency_ms',
            'actor_id',
            'idempotency_key',
            'outcome_detail'
        ]
        for key in required_keys:
            self.assertIn(key, log_data, f"Structured log is missing required key '{key}'")

        self.assertEqual(log_data['correlation_id'], "test-corr-id-123")
        self.assertEqual(log_data['chain_name'], "test_chain")
        self.assertEqual(log_data['step'], "test_step")
        self.assertEqual(log_data['outcome'], "success")
        self.assertEqual(log_data['latency_ms'], 12.34)
        self.assertEqual(log_data['actor_id'], "test_actor")
        self.assertEqual(log_data['idempotency_key'], "V100")


if __name__ == '__main__':
    unittest.main()
