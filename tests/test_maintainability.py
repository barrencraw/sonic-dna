import inspect
import unittest
import io
import sys
import json
from utils.dna_calculator import DNACalculator
from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    RuleLoadError,
    InputReadError,
    PersistenceError,
    LedgerSaveError,
    AtomicWriteError,
    log_structured
)

class TestMaintainability(unittest.TestCase):
    def test_canonical_naming_parameter(self):
        """Assert that DNACalculator.parse accepts `dna_sequence` as a canonical parameter."""
        sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', sig.parameters, "DNACalculator.parse must use canonical parameter name 'dna_sequence'")

    def test_exception_hierarchy(self):
        """Assert typed exception hierarchy and error classification."""
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_dna_status_enum_values(self):
        """Assert DNAStatus Enum canonical values."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")

    def test_structured_logging_fields(self):
        """Assert structured log JSON formatting and mandatory key presence."""
        stdout_trap = io.StringIO()
        sys.stdout = stdout_trap
        try:
            log_entry = log_structured(
                correlation_id="test-corr-123",
                chain_name="dna_batch_parser",
                step="parse_sequence",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=12.34,
                actor_id="unit_test",
                idempotency_key="VOL08900750712",
                outcome_detail="Rule parsed successfully"
            )
        finally:
            sys.stdout = sys.__stdout__

        output = stdout_trap.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "))
        raw_json = output.replace("JSON_LOG: ", "")
        parsed = json.loads(raw_json)

        mandatory_fields = [
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        ]
        for field in mandatory_fields:
            self.assertIn(field, parsed)
            self.assertIn(field, log_entry)

        self.assertEqual(parsed["correlation_id"], "test-corr-123")
        self.assertEqual(parsed["outcome"], "success")

if __name__ == '__main__':
    unittest.main()
