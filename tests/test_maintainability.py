import unittest
import json
import io
import sys
from utils.dna_calculator import ParsedDNA
from utils.dna_ui import Outcome, log_observability

class TestMaintainability(unittest.TestCase):
    def test_parsed_dna_dto(self):
        """Verify the ParsedDNA dataclass structure."""
        dto = ParsedDNA(dna="V100", rule="Volume", values={"level": 100})
        self.assertEqual(dto.dna, "V100")
        self.assertEqual(dto.rule, "Volume")
        self.assertEqual(dto.values, {"level": 100})

    def test_outcome_enum(self):
        """Verify Outcome Enum members."""
        expected = {"START", "END", "SUCCESS", "ERROR", "SKIPPED", "PROCESSING"}
        actual = {m.name for m in Outcome}
        self.assertTrue(expected.issubset(actual))

    def test_telemetry_schema(self):
        """Verify that log_observability outputs valid pipe-delimited JSON."""
        captured_output = io.StringIO()
        sys.stdout = captured_output
        try:
            log_observability(step="test_step", outcome=Outcome.SUCCESS.value, correlation_id="test-id", extra={"foo": "bar"})
        finally:
            sys.stdout = sys.__stdout__

        output = captured_output.getvalue().strip()
        self.assertTrue(output.startswith("| TELEMETRY | "))

        json_str = output.replace("| TELEMETRY | ", "")
        data = json.loads(json_str)

        self.assertEqual(data["step"], "test_step")
        self.assertEqual(data["outcome"], "SUCCESS")
        self.assertEqual(data["correlation_id"], "test-id")
        self.assertEqual(data["foo"], "bar")
        self.assertEqual(data["chain_name"], "dna_batch_chain")
        self.assertIn("timestamp", data)

if __name__ == '__main__':
    unittest.main()
