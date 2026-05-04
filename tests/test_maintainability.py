import unittest
import json
import io
from contextlib import redirect_stdout
from utils.dna_calculator import ParsedDNA
from utils.dna_ui import Outcome, log_observability

class TestMaintainability(unittest.TestCase):
    def test_parsed_dna_dto(self):
        """Ensure ParsedDNA DTO has the expected fields."""
        dto = ParsedDNA(dna="V100", rule="Volume", values={"level": 100})
        self.assertEqual(dto.dna, "V100")
        self.assertEqual(dto.rule, "Volume")
        self.assertEqual(dto.values["level"], 100)

    def test_outcome_enum(self):
        """Ensure Outcome Enum has the required terminal and intermediate states."""
        expected_states = {"START", "END", "SUCCESS", "ERROR", "SKIPPED"}
        actual_states = {o.name for o in Outcome}
        for state in expected_states:
            self.assertIn(state, actual_states)

    def test_log_observability_schema(self):
        """Ensure log_observability outputs correctly formatted JSON telemetry."""
        f = io.StringIO()
        with redirect_stdout(f):
            log_observability(
                correlation_id="test-id",
                step="TestStep",
                outcome=Outcome.SUCCESS,
                extra={"key": "value"}
            )
        output = f.getvalue().strip()
        self.assertTrue(output.startswith("| TELEMETRY | "))

        json_part = output.replace("| TELEMETRY | ", "")
        log_data = json.loads(json_part)

        self.assertEqual(log_data["correlation_id"], "test-id")
        self.assertEqual(log_data["step"], "TestStep")
        self.assertEqual(log_data["outcome"], "SUCCESS")
        self.assertEqual(log_data["key"], "value")
        self.assertIn("timestamp", log_data)
        self.assertEqual(log_data["actor_id"], "system")
        self.assertEqual(log_data["chain_name"], "dna_batch_chain")

    def test_log_observability_with_latency(self):
        """Ensure log_observability includes latency_ms when provided."""
        f = io.StringIO()
        with redirect_stdout(f):
            log_observability(
                correlation_id="test-id",
                step="TestStep",
                outcome=Outcome.SUCCESS,
                latency_ms=123
            )
        output = f.getvalue().strip()
        json_part = output.replace("| TELEMETRY | ", "")
        log_data = json.loads(json_part)
        self.assertEqual(log_data["latency_ms"], 123)

if __name__ == '__main__':
    unittest.main()
