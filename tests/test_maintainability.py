import unittest
import os
import shutil
import tempfile
import json
import io
import sys
from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    InputReadError,
    RuleLoadError,
    LedgerLoadError,
    LedgerSaveError,
    PersistenceError,
    AtomicWriteError,
    run_batch,
    log_structured
)
from utils.dna_calculator import DNACalculator, RuleParseError
import inspect


class TestMaintainability(unittest.TestCase):
    def test_typed_exceptions_taxonomy(self):
        """Ensure exception taxonomy is properly inheritance-hierarchied under DNAProcessingError."""
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_dna_status_lowercase_values(self):
        """Ensure DNAStatus string values are canonical lowercase for backwards compatibility."""
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")
        self.assertEqual(DNAStatus.REFUSED, "refused")

    def test_canonical_naming_alignment(self):
        """Verify method signatures and docstrings use canonical dna_sequence terminology."""
        from utils.dna_calculator import Rule
        calc_sig = inspect.signature(DNACalculator.parse)
        self.assertIn("dna_sequence", calc_sig.parameters)

        rule_parse_sig = inspect.signature(Rule.parse)
        self.assertIn("dna_sequence", rule_parse_sig.parameters)

        # Verify DNACalculator docstring
        doc = DNACalculator.parse.__doc__
        self.assertIsNotNone(doc)
        self.assertIn("DNA sequence", doc)

    def test_structured_log_fields_presence(self):
        """Verify structured logs emit mandatory observability telemetry fields."""
        captured_stdout = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = captured_stdout
            log_structured(
                correlation_id="test-corr-123",
                chain_name="dna_batch_parsing",
                step="parse_sequence",
                outcome=DNAStatus.SUCCESS,
                latency_ms=12,
                actor_id="test_actor",
                idempotency_key="VOL08900750712",
                outcome_detail="Testing structured log"
            )
        finally:
            sys.stdout = old_stdout

        output = captured_stdout.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG:"))

        json_str = output[len("JSON_LOG:"):]
        payload = json.loads(json_str)

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
            self.assertIn(key, payload, f"Missing required log key: {key}")

        self.assertEqual(payload["correlation_id"], "test-corr-123")
        self.assertEqual(payload["chain_name"], "dna_batch_parsing")
        self.assertEqual(payload["step"], "parse_sequence")
        self.assertEqual(payload["outcome"], "success")
        self.assertEqual(payload["latency_ms"], 12)
        self.assertEqual(payload["actor_id"], "test_actor")
        self.assertEqual(payload["idempotency_key"], "VOL08900750712")


if __name__ == '__main__':
    unittest.main()
