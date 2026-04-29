import unittest
import json
import os
import io
from contextlib import redirect_stdout
from utils.dna_calculator import ParsedDNA, DNACalculator
from utils.dna_ui import Outcome, log_observability

class TestMaintainability(unittest.TestCase):
    def test_parsed_dna_dto(self):
        """Verify ParsedDNA dataclass structure."""
        dto = ParsedDNA(dna="TEST", rule="TestRule", values={"a": 1})
        self.assertEqual(dto.dna, "TEST")
        self.assertEqual(dto.rule, "TestRule")
        self.assertEqual(dto.values["a"], 1)

    def test_outcome_enum(self):
        """Verify Outcome Enum members."""
        expected = ["START", "END", "SUCCESS", "ERROR", "SKIPPED", "PROCESSING", "PARTIAL_SUCCESS", "NO_NEW_DNA"]
        for name in expected:
            self.assertTrue(hasattr(Outcome, name))

    def test_log_observability_schema(self):
        """Verify telemetry log format and schema."""
        f = io.StringIO()
        with redirect_stdout(f):
            log_observability("test_step", Outcome.SUCCESS, correlation_id="123", dna="VOL123")

        output = f.getvalue().strip()
        self.assertTrue(output.startswith("| TELEMETRY |"))

        json_part = output.replace("| TELEMETRY |", "").strip()
        data = json.loads(json_part)

        self.assertEqual(data["correlation_id"], "123")
        self.assertEqual(data["step"], "test_step")
        self.assertEqual(data["outcome"], "SUCCESS")
        self.assertEqual(data["dna"], "VOL123")
        self.assertEqual(data["actor_id"], "system")
        self.assertIn("timestamp", data)

if __name__ == '__main__':
    unittest.main()
