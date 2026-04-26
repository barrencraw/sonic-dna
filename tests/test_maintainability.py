import unittest
import json
import sys
import io
from utils.dna_calculator import ParsedDNA
from utils.dna_ui import Outcome, log_observability

class TestMaintainability(unittest.TestCase):
    def test_parsed_dna_dataclass(self):
        """Verify ParsedDNA naming alignment."""
        dna = "VOL08900750712"
        rule = "Volume"
        values = {"amp": 890, "lr": 75, "sur": 7, "head": 12}
        obj = ParsedDNA(dna=dna, rule=rule, values=values)

        self.assertEqual(obj.dna, dna)
        self.assertEqual(obj.rule, rule)
        self.assertEqual(obj.values, values)

    def test_outcome_enum(self):
        """Verify Outcome Enum members."""
        self.assertEqual(Outcome.START.value, "START")
        self.assertEqual(Outcome.END.value, "END")
        self.assertEqual(Outcome.SUCCESS.value, "SUCCESS")
        self.assertEqual(Outcome.ERROR.value, "ERROR")
        self.assertEqual(Outcome.SKIPPED.value, "SKIPPED")
        self.assertEqual(Outcome.PROCESSING.value, "PROCESSING")

    def test_log_observability_schema(self):
        """Verify structured log format."""
        captured_output = io.StringIO()
        sys.stdout = captured_output

        log_observability(
            step="test_step",
            outcome=Outcome.SUCCESS,
            dna="TESTDNA",
            rule="TestRule",
            correlation_id="123-abc",
            latency_ms=42.5
        )

        sys.stdout = sys.__stdout__
        output = captured_output.getvalue().strip()

        self.assertTrue(output.startswith("| TELEMETRY | "))
        json_part = output.replace("| TELEMETRY | ", "")
        data = json.loads(json_part)

        self.assertEqual(data["step"], "test_step")
        self.assertEqual(data["outcome"], "SUCCESS")
        self.assertEqual(data["dna"], "TESTDNA")
        self.assertEqual(data["rule"], "TestRule")
        self.assertEqual(data["correlation_id"], "123-abc")
        self.assertEqual(data["latency_ms"], 42.5)
        self.assertIn("timestamp", data)

if __name__ == '__main__':
    unittest.main()
