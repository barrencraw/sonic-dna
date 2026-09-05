import os
import json
import unittest
import io
from contextlib import redirect_stdout
from utils.dna_calculator import DNACalculator
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
    def test_dnastatus_enum_values(self):
        """Verify explicit terminal status enum utilizes canonical lowercase string values."""
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")
        self.assertEqual(DNAStatus.REFUSED, "refused")

    def test_exception_taxonomy_hierarchy(self):
        """Verify typed error classification hierarchy."""
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_canonical_naming_in_calculator(self):
        """Verify DNACalculator accepts `dna_sequence` keyword argument."""
        calculator = DNACalculator(rules_folder='rules')
        # Volume rule prefix 'VOL'
        result = calculator.parse(dna_sequence="VOL08900750712")
        self.assertEqual(result['rule'], "Volume")

    def test_structured_logging_schema(self):
        """Verify structured log utility outputs mandatory telemetry fields."""
        f = io.StringIO()
        with redirect_stdout(f):
            log_structured(
                correlation_id="test-corr-123",
                chain_name="dna_batch_parsing",
                step="parse_sequence",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=12.34,
                actor_id="test_actor",
                idempotency_key="VOL08900750712",
                outcome_detail="Parsed successfully"
            )
        output = f.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG:"))

        json_str = output[len("JSON_LOG:"):]
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
            self.assertIn(key, data, f"Missing required telemetry log key: {key}")

        self.assertEqual(data["correlation_id"], "test-corr-123")
        self.assertEqual(data["actor_id"], "test_actor")
        self.assertEqual(data["chain_name"], "dna_batch_parsing")
        self.assertEqual(data["step"], "parse_sequence")
        self.assertEqual(data["outcome"], "success")

if __name__ == '__main__':
    unittest.main()
