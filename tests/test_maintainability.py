import unittest
import json
import os
from utils.dna_calculator import ParsedDNA
from utils.dna_ui import Outcome, log_observability
from io import StringIO
import sys

class TestMaintainability(unittest.TestCase):
    def test_parsed_dna_dataclass(self):
        pd = ParsedDNA(dna="DNA123", rule="TestRule", values={"a": 1})
        self.assertEqual(pd.dna, "DNA123")
        self.assertEqual(pd.rule, "TestRule")
        self.assertEqual(pd.values["a"], 1)

    def test_outcome_enum(self):
        self.assertEqual(Outcome.SUCCESS.value, "SUCCESS")
        self.assertEqual(Outcome.ERROR.value, "ERROR")
        self.assertIn("SKIPPED", [o.name for o in Outcome])

    def test_log_observability_schema(self):
        # Capture stdout
        captured_output = StringIO()
        sys.stdout = captured_output
        try:
            log_observability(
                chain_name="TestChain",
                step="TestStep",
                outcome=Outcome.SUCCESS,
                correlation_id="test-id",
                idempotency_key="test-key"
            )
        finally:
            sys.stdout = sys.__stdout__

        log_json = json.loads(captured_output.getvalue().strip())

        expected_keys = {
            "timestamp", "correlation_id", "chain_name", "step",
            "outcome", "latency_ms", "actor_id", "idempotency_key"
        }
        self.assertTrue(expected_keys.issubset(set(log_json.keys())))
        self.assertEqual(log_json["chain_name"], "TestChain")
        self.assertEqual(log_json["outcome"], "SUCCESS")
        self.assertEqual(log_json["correlation_id"], "test-id")
        self.assertEqual(log_json["idempotency_key"], "test-key")

if __name__ == "__main__":
    unittest.main()
