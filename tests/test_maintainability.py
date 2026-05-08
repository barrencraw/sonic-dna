import unittest
import json
import io
import contextlib
from utils.dna_calculator import ParsedDNA, DNACalculator
from utils.dna_ui import Outcome, log_observability

class TestMaintainability(unittest.TestCase):
    def test_parsed_dna_dto(self):
        """Ensure ParsedDNA DTO has expected fields."""
        dto = ParsedDNA(dna="TEST", rule="TestRule", values={"k": "v"})
        self.assertEqual(dto.dna, "TEST")
        self.assertEqual(dto.rule, "TestRule")
        self.assertEqual(dto.values["k"], "v")

    def test_outcome_enum(self):
        """Ensure Outcome enum has canonical states."""
        expected = {"START", "END", "SUCCESS", "ERROR", "SKIPPED"}
        actual = {o.name for o in Outcome}
        self.assertEqual(expected, actual)

    def test_log_observability_schema(self):
        """Ensure log_observability output contains required fields."""
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            log_observability(
                outcome=Outcome.SUCCESS,
                step="test_step",
                correlation_id="123",
                idempotency_key="abc",
                latency_ms=10.5
            )

        output = f.getvalue().strip()
        self.assertTrue(output.startswith("| TELEMETRY |"))

        json_part = output.replace("| TELEMETRY | ", "")
        data = json.loads(json_part)

        self.assertEqual(data["outcome"], "SUCCESS") # Enum value is 'success', but log should be upper
        self.assertEqual(data["step"], "test_step")
        self.assertEqual(data["correlation_id"], "123")
        self.assertEqual(data["idempotency_key"], "abc")
        self.assertEqual(data["latency_ms"], 10.5)
        self.assertIn("timestamp", data)
        self.assertIn("chain_name", data)
        self.assertIn("actor_id", data)

if __name__ == "__main__":
    unittest.main()
