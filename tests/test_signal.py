import unittest
import json
import io
from contextlib import redirect_stdout
from utils.dna_calculator import ParsedDNA
from utils.dna_ui import log_observability, Outcome

class TestSignal(unittest.TestCase):
    def test_parsed_dna_dto(self):
        """Verify ParsedDNA DTO structure."""
        dto = ParsedDNA(dna="TEST", rule="TestRule", values={"a": 1})
        self.assertEqual(dto.dna, "TEST")
        self.assertEqual(dto.rule, "TestRule")
        self.assertEqual(dto.values, {"a": 1})

    def test_log_observability_schema(self):
        """Verify log_observability follows the standard schema."""
        f = io.StringIO()
        with redirect_stdout(f):
            log_observability(
                correlation_id="test-id",
                chain_name="test-chain",
                step="test-step",
                outcome=Outcome.SUCCESS,
                latency_ms=100,
                idempotency_key="test-key"
            )
        output = f.getvalue().strip()
        self.assertTrue(output.startswith("[OBSERVABILITY] "))
        log_json = json.loads(output.replace("[OBSERVABILITY] ", ""))

        required_keys = [
            "timestamp", "correlation_id", "chain_name", "step",
            "outcome", "latency_ms", "actor_id", "idempotency_key"
        ]
        for key in required_keys:
            self.assertIn(key, log_json)

        self.assertEqual(log_json["correlation_id"], "test-id")
        self.assertEqual(log_json["chain_name"], "test-chain")
        self.assertEqual(log_json["outcome"], "SUCCESS")

if __name__ == "__main__":
    unittest.main()
