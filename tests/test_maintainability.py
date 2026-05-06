import unittest
import json
from utils.dna_calculator import ParsedDNA, DNACalculator
from utils.dna_ui import Outcome, log_observability
from io import StringIO
import sys

class TestMaintainability(unittest.TestCase):
    def test_parsed_dna_dto(self):
        """Verify ParsedDNA DTO schema."""
        dto = ParsedDNA(dna="V100", rule="Volume", values={"level": 100})
        self.assertEqual(dto.dna, "V100")
        self.assertEqual(dto.rule, "Volume")
        self.assertEqual(dto.values["level"], 100)

    def test_outcome_enum(self):
        """Verify Outcome Enum members."""
        expected = {"START", "END", "SUCCESS", "ERROR", "SKIPPED"}
        actual = {m.name for m in Outcome}
        self.assertEqual(expected, actual)

    def test_log_observability_schema(self):
        """Verify log_observability structured output schema."""
        captured_output = StringIO()
        sys.stdout = captured_output
        try:
            log_observability(
                step="Test Step",
                outcome=Outcome.SUCCESS,
                correlation_id="test-uuid",
                latency_ms=123.456,
                idempotency_key="test-key"
            )
        finally:
            sys.stdout = sys.__stdout__

        output = captured_output.getvalue().strip()
        self.assertTrue(output.startswith("| TELEMETRY | "))

        json_str = output.replace("| TELEMETRY | ", "")
        data = json.loads(json_str)

        expected_keys = {
            "timestamp", "correlation_id", "chain_name",
            "step", "outcome", "actor_id", "latency_ms", "idempotency_key"
        }
        self.assertTrue(expected_keys.issubset(data.keys()))
        self.assertEqual(data["outcome"], "SUCCESS")
        self.assertEqual(data["latency_ms"], 123.46) # Rounded

if __name__ == "__main__":
    unittest.main()
