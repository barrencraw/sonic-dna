import os
import json
import io
import sys
import unittest
from unittest.mock import patch, MagicMock

from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    RuleLoadError,
    PersistenceError,
    InputReadError,
    LedgerSaveError,
    AtomicWriteError,
    log_structured,
    run_batch
)
from utils.dna_calculator import DNACalculator, RuleParseError


class TestMaintainabilityAndSignal(unittest.TestCase):
    def test_dnastatus_terminal_states(self):
        """Verify explicit string values of DNAStatus enum."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")

    def test_typed_exception_hierarchy(self):
        """Verify typed error inheritance hierarchy."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_structured_log_field_presence(self):
        """Verify structured log output contains all mandatory observability fields."""
        captured_output = io.StringIO()
        with patch('sys.stdout', new=captured_output):
            log_structured(
                correlation_id="test-corr-123",
                chain_name="dna_batch_parser",
                step="parse_sequence",
                outcome=DNAStatus.SUCCESS,
                latency_ms=12.34,
                actor_id="test_actor",
                idempotency_key="V100",
                outcome_detail="Parsed successfully"
            )

        output = captured_output.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "))
        json_str = output[len("JSON_LOG: "):]
        log_data = json.loads(json_str)

        required_keys = [
            "timestamp",
            "correlation_id",
            "chain_name",
            "step",
            "outcome",
            "latency_ms",
            "actor_id",
            "idempotency_key",
            "outcome_detail"
        ]
        for key in required_keys:
            self.assertIn(key, log_data, f"Missing required log key: {key}")

        self.assertEqual(log_data["correlation_id"], "test-corr-123")
        self.assertEqual(log_data["chain_name"], "dna_batch_parser")
        self.assertEqual(log_data["step"], "parse_sequence")
        self.assertEqual(log_data["outcome"], "success")
        self.assertEqual(log_data["actor_id"], "test_actor")
        self.assertEqual(log_data["idempotency_key"], "V100")

    def test_canonical_dna_sequence_naming(self):
        """Verify parse method parameter naming alignment and dictionary structure."""
        calc = DNACalculator(rules_folder='rules')
        # Check method signature accepts dna_sequence
        result = calc.parse(dna_sequence="VOL08900750712")
        self.assertEqual(result['rule'], "Volume")


if __name__ == '__main__':
    unittest.main()
