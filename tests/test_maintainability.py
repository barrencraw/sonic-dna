import unittest
from utils.dna_calculator import ParsedDNA
from utils.dna_ui import Outcome, log_observability
import json
import io
from contextlib import redirect_stdout

class TestMaintainability(unittest.TestCase):
    def test_parsed_dna_dto(self):
        # Ensure ParsedDNA has expected fields
        dto = ParsedDNA(dna="VOL100", rule="Volume", values={"level": 100})
        self.assertEqual(dto.dna, "VOL100")
        self.assertEqual(dto.rule, "Volume")
        self.assertEqual(dto.values, {"level": 100})

    def test_outcome_enum(self):
        # Ensure Outcome enum has canonical states
        self.assertTrue(hasattr(Outcome, 'SUCCESS'))
        self.assertTrue(hasattr(Outcome, 'ERROR'))
        self.assertTrue(hasattr(Outcome, 'SKIPPED'))
        self.assertEqual(Outcome.SUCCESS.value, "SUCCESS")

    def test_log_observability_schema(self):
        # Verify log_observability outputs expected JSON structure
        f = io.StringIO()
        with redirect_stdout(f):
            log_observability(
                correlation_id="test-id",
                chain_name="test-chain",
                step="test-step",
                outcome=Outcome.SUCCESS,
                latency_ms=100.5,
                actor_id="test-actor",
                idempotency_key="test-key",
                extra={"foo": "bar"}
            )
        output = f.getvalue().strip()
        self.assertTrue(output.startswith("| TELEMETRY | "))
        json_str = output.replace("| TELEMETRY | ", "")
        data = json.loads(json_str)

        expected_keys = ["correlation_id", "chain_name", "step", "outcome", "latency_ms", "actor_id", "timestamp", "idempotency_key", "foo"]
        for key in expected_keys:
            self.assertIn(key, data)

        self.assertEqual(data["correlation_id"], "test-id")
        self.assertEqual(data["outcome"], "SUCCESS")
        self.assertEqual(data["foo"], "bar")

if __name__ == '__main__':
    unittest.main()
