import unittest
import io
import sys
import json
import inspect
from utils.dna_calculator import DNACalculator, Rule
from utils.dna_ui import (
    log_structured,
    run_batch,
    DNAStatus,
    DNAProcessingError,
    InputReadError,
    PersistenceError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError
)

class TestMaintainabilityRegression(unittest.TestCase):
    def test_naming_alignment_dna_sequence_parameter(self):
        """Verify that parse methods accept 'dna_sequence' parameter name."""
        calc_sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', calc_sig.parameters, "DNACalculator.parse must use parameter 'dna_sequence'")

        rule_sig = inspect.signature(Rule.parse)
        self.assertIn('dna_sequence', rule_sig.parameters, "Rule.parse must use parameter 'dna_sequence'")

    def test_typed_exceptions_hierarchy(self):
        """Verify typed error classification hierarchy."""
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_dna_status_enum(self):
        """Verify DNAStatus enum string values."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_structured_logging_keys(self):
        """Verify structured log emission format and standard fields."""
        captured_output = io.StringIO()
        sys.stdout = captured_output

        try:
            log_structured(
                correlation_id="test-cid-123",
                actor_id="test-actor",
                chain_name="test_chain",
                step="test_step",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=12.34,
                idempotency_key="VOL123",
                outcome_detail="Parsed successfully"
            )
        finally:
            sys.stdout = sys.__stdout__

        output = captured_output.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "))

        json_str = output[len("JSON_LOG: "):]
        data = json.loads(json_str)

        required_keys = {
            'timestamp',
            'correlation_id',
            'actor_id',
            'chain_name',
            'step',
            'outcome',
            'latency_ms',
            'idempotency_key',
            'outcome_detail'
        }
        self.assertTrue(required_keys.issubset(data.keys()), f"Missing required log keys. Got: {set(data.keys())}")
        self.assertEqual(data['correlation_id'], "test-cid-123")
        self.assertEqual(data['actor_id'], "test-actor")
        self.assertEqual(data['chain_name'], "test_chain")
        self.assertEqual(data['step'], "test_step")
        self.assertEqual(data['outcome'], "success")
        self.assertEqual(data['latency_ms'], 12.34)
        self.assertEqual(data['idempotency_key'], "VOL123")
        self.assertEqual(data['outcome_detail'], "Parsed successfully")

if __name__ == '__main__':
    unittest.main()
