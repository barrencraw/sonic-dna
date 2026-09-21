import os
import sys
import json
import io
import unittest
from unittest.mock import patch

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
    log_structured,
    main as run_batch
)


class TestMaintainabilityAndRegression(unittest.TestCase):
    def test_dna_status_values(self):
        """Verify that DNAStatus enum maintains canonical lowercase string values."""
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")
        self.assertEqual(DNAStatus.REFUSED, "refused")

    def test_exception_hierarchy(self):
        """Verify typed error inheritance under DNAProcessingError and PersistenceError."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_structured_log_keys(self):
        """Verify structured log output format and required keys."""
        buf = io.StringIO()
        with patch('sys.stdout', new=buf):
            log_structured(
                correlation_id="test-corr-id",
                step="test_step",
                outcome=DNAStatus.SUCCESS,
                latency_ms=42,
                actor_id="test_actor",
                idempotency_key="V100",
                outcome_detail="Detail message"
            )

        output = buf.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "))
        json_str = output[len("JSON_LOG: "):]
        log_obj = json.loads(json_str)

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
            self.assertIn(key, log_obj, f"Missing required log key: {key}")

        self.assertEqual(log_obj["correlation_id"], "test-corr-id")
        self.assertEqual(log_obj["chain_name"], "dna_batch_parser")
        self.assertEqual(log_obj["outcome"], "success")

    def test_dna_sequence_naming_in_calculator(self):
        """Verify that DNACalculator.parse accepts dna_sequence as keyword argument."""
        calc = DNACalculator(rules_folder='rules')
        # Test keyword argument dna_sequence
        result = calc.parse(dna_sequence="VOL08900750712")
        self.assertEqual(result['rule'], 'Volume')


if __name__ == '__main__':
    unittest.main()
