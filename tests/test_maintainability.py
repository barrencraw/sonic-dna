import os
import json
import unittest
import io
from contextlib import redirect_stdout

from utils.dna_calculator import DNACalculator
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

class TestMaintainabilityAndSignal(unittest.TestCase):
    def test_dna_calculator_naming_alignment(self):
        """Verify that DNACalculator.parse accepts dna_sequence keyword parameter."""
        calculator = DNACalculator(rules_folder='rules')
        result = calculator.parse(dna_sequence="VOL08900750712")
        self.assertEqual(result['rule'], 'Volume')

    def test_exception_taxonomy_hierarchy(self):
        """Verify exception class inheritance hierarchy for typed error classification."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_dna_status_enum_values(self):
        """Verify explicit terminal states defined in DNAStatus string enum."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")

    def test_structured_logging_fields(self):
        """Verify structured log output format and required log key presence."""
        f = io.StringIO()
        with redirect_stdout(f):
            log_structured(
                correlation_id="test_corr_123",
                chain_name="dna_batch_parser",
                step="parse_sequence",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=12,
                actor_id="test_runner",
                idempotency_key="VOL08900750712",
                outcome_detail="rule=Volume"
            )
        output = f.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG:"))

        log_json_str = output[len("JSON_LOG:"):]
        log_data = json.loads(log_json_str)

        required_keys = {
            "timestamp",
            "correlation_id",
            "chain_name",
            "step",
            "outcome",
            "latency_ms",
            "actor_id",
            "idempotency_key",
            "outcome_detail"
        }
        self.assertTrue(required_keys.issubset(set(log_data.keys())))
        self.assertEqual(log_data["correlation_id"], "test_corr_123")
        self.assertEqual(log_data["chain_name"], "dna_batch_parser")
        self.assertEqual(log_data["step"], "parse_sequence")
        self.assertEqual(log_data["outcome"], "success")
        self.assertEqual(log_data["latency_ms"], 12)
        self.assertEqual(log_data["actor_id"], "test_runner")
        self.assertEqual(log_data["idempotency_key"], "VOL08900750712")
        self.assertEqual(log_data["outcome_detail"], "rule=Volume")

if __name__ == '__main__':
    unittest.main()
