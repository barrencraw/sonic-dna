import unittest
import json
import io
from contextlib import redirect_stdout
from utils.dna_ui import Outcome, ParsedDNA, log_observability

class TestMaintainability(unittest.TestCase):
    def test_outcome_enum_values(self):
        self.assertEqual(Outcome.SUCCESS.value, "success")
        self.assertEqual(Outcome.SKIPPED.value, "skipped")
        self.assertEqual(Outcome.ERROR.value, "error")

    def test_parsed_dna_dto(self):
        dto = ParsedDNA(
            dna="TEST_DNA",
            outcome=Outcome.SUCCESS,
            rule="TestRule",
            values={"key": "value"}
        )
        self.assertEqual(dto.dna, "TEST_DNA")
        self.assertEqual(dto.outcome, Outcome.SUCCESS)
        self.assertEqual(dto.rule, "TestRule")
        self.assertEqual(dto.values, {"key": "value"})
        self.assertIsNone(dto.error)

    def test_log_observability_schema(self):
        f = io.StringIO()
        with redirect_stdout(f):
            log_observability(
                step="TestStep",
                outcome=Outcome.SUCCESS,
                correlation_id="test-id",
                idempotency_key="test-key",
                data={"foo": "bar"}
            )

        output = f.getvalue().strip()
        self.assertTrue(output.startswith("| TELEMETRY | "))
        log_json = json.loads(output.replace("| TELEMETRY | ", ""))

        required_keys = {
            "timestamp", "correlation_id", "chain_name",
            "step", "outcome", "latency_ms",
            "actor_id", "idempotency_key", "data"
        }
        for key in required_keys:
            self.assertIn(key, log_json)

        self.assertEqual(log_json["step"], "TestStep")
        self.assertEqual(log_json["outcome"], "SUCCESS")
        self.assertEqual(log_json["correlation_id"], "test-id")
        self.assertEqual(log_json["idempotency_key"], "test-key")
        self.assertEqual(log_json["data"], {"foo": "bar"})

if __name__ == "__main__":
    unittest.main()
