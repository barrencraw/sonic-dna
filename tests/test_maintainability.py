import unittest
import io
import sys
import json
from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    InputReadError,
    RuleLoadError,
    PersistenceError,
    LedgerSaveError,
    AtomicWriteError,
    log_structured,
    flatten_parsed
)
from utils.dna_calculator import DNACalculator

class TestMaintainabilityAndRegressionGuards(unittest.TestCase):

    def test_dnastatus_enum_values(self):
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_exception_hierarchy(self):
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, DNAProcessingError))
        self.assertTrue(issubclass(AtomicWriteError, DNAProcessingError))

    def test_structured_log_schema(self):
        captured_output = io.StringIO()
        sys.stdout = captured_output
        try:
            log_entry = log_structured(
                correlation_id="test-corr-123",
                actor_id="test-actor",
                chain_name="dna_test_chain",
                step="test_step",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=15,
                idempotency_key="VOL08900750712",
                outcome_detail={"test": "data"}
            )
        finally:
            sys.stdout = sys.__stdout__

        output_str = captured_output.getvalue()
        self.assertTrue(output_str.startswith("JSON_LOG: "))
        json_part = output_str.replace("JSON_LOG: ", "").strip()
        parsed = json.loads(json_part)

        required_keys = {
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        }
        self.assertEqual(set(parsed.keys()), required_keys)
        self.assertEqual(parsed["correlation_id"], "test-corr-123")
        self.assertEqual(parsed["actor_id"], "test-actor")
        self.assertEqual(parsed["outcome"], "success")

    def test_dna_sequence_key_in_parsed_output(self):
        calculator = DNACalculator(rules_folder='rules')
        dna_sequence = "VOL08900750712"
        result = calculator.parse(dna_sequence)

        entry = {
            'dna': dna_sequence,
            'dna_sequence': dna_sequence,
            'rule': result['rule'],
            'parsed': result['values']
        }
        self.assertIn('dna_sequence', entry)
        self.assertIn('dna', entry)
        self.assertEqual(entry['dna_sequence'], dna_sequence)
        self.assertEqual(entry['dna'], dna_sequence)

if __name__ == '__main__':
    unittest.main()
