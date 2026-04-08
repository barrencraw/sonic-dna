import unittest
import json
import io
import contextlib
from utils.dna_calculator import ParsedDNA
from utils.dna_ui import log_observability, Outcome

class TestSignal(unittest.TestCase):
    def test_parsed_dna_dto(self):
        """Verify the ParsedDNA DTO structure."""
        dna = "VOL0890"
        rule = "Volume"
        values = {"amp": 890}
        parsed = ParsedDNA(dna=dna, rule=rule, values=values)

        self.assertEqual(parsed.dna, dna)
        self.assertEqual(parsed.rule, rule)
        self.assertEqual(parsed.values, values)

    def test_log_observability_schema(self):
        """Verify the structured log output schema."""
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            log_observability(
                correlation_id="test-corr",
                actor_id="test-actor",
                step="test-step",
                outcome=Outcome.SUCCESS,
                latency_ms=123.45,
                idempotency_key="test-key",
                error_message="test-error"
            )

        output = f.getvalue().strip()
        self.assertTrue(output.startswith("[OBSERVABILITY] "))

        log_json = json.loads(output[len("[OBSERVABILITY] "):])

        required_keys = {
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "error_message"
        }
        for key in required_keys:
            self.assertIn(key, log_json)

        self.assertEqual(log_json["correlation_id"], "test-corr")
        self.assertEqual(log_json["actor_id"], "test-actor")
        self.assertEqual(log_json["step"], "test-step")
        self.assertEqual(log_json["outcome"], "SUCCESS")
        self.assertEqual(log_json["latency_ms"], 123)
        self.assertEqual(log_json["idempotency_key"], "test-key")
        self.assertEqual(log_json["error_message"], "test-error")
        self.assertEqual(log_json["chain_name"], "dna_batch_chain")

if __name__ == "__main__":
    unittest.main()
