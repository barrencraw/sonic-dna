import unittest
import json
import io
import contextlib
from utils.dna_calculator import ParsedDNA
from utils.dna_ui import log_observability, Outcome

class TestSignal(unittest.TestCase):
    def test_parsed_dna_dto(self):
        """Assert ParsedDNA DTO structure."""
        p = ParsedDNA(dna="VOL1234", rule="Volume", values={"amp": 1234})
        self.assertEqual(p.dna, "VOL1234")
        self.assertEqual(p.rule, "Volume")
        self.assertEqual(p.values["amp"], 1234)

    def test_log_observability_schema(self):
        """Assert log_observability produces valid JSON with required keys."""
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            log_observability(
                step="TEST_STEP",
                outcome=Outcome.SUCCESS,
                correlation_id="test-corr-id",
                idempotency_key="test-key"
            )

        output = f.getvalue().strip()
        log_entry = json.loads(output)

        required_keys = {
            "timestamp", "correlation_id", "chain_name", "step",
            "outcome", "latency_ms", "actor_id", "idempotency_key"
        }
        for key in required_keys:
            self.assertIn(key, log_entry, f"Missing required log key: {key}")

        self.assertEqual(log_entry["outcome"], "SUCCESS")
        self.assertEqual(log_entry["correlation_id"], "test-corr-id")
        self.assertEqual(log_entry["idempotency_key"], "test-key")

if __name__ == "__main__":
    unittest.main()
