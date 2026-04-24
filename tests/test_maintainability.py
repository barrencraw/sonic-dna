import unittest
import os
import sys
import io
import json
from utils.dna_calculator import DNACalculator, ParsedDNA
from utils.dna_ui import Outcome, log_observability

class TestMaintainability(unittest.TestCase):
    def test_parsed_dna_dto(self):
        """Verify ParsedDNA DTO exists and has expected fields."""
        dto = ParsedDNA(dna="TEST", rule="TestRule", values={"a": 1})
        self.assertEqual(dto.dna, "TEST")
        self.assertEqual(dto.rule, "TestRule")
        self.assertEqual(dto.values, {"a": 1})

    def test_outcome_enum(self):
        """Verify Outcome Enum has required members."""
        expected = ["SUCCESS", "ERROR", "SKIPPED", "PARTIAL_SUCCESS", "NO_NEW_DNA", "START", "PROCESSING"]
        for name in expected:
            with self.subTest(name=name):
                self.assertTrue(hasattr(Outcome, name))

    def test_log_observability_schema(self):
        """Verify log_observability emits expected structured format."""
        captured_output = io.StringIO()
        sys.stdout = captured_output
        try:
            log_observability(
                chain_name="test_chain",
                step="test_step",
                outcome=Outcome.SUCCESS,
                correlation_id="test_id"
            )
        finally:
            sys.stdout = sys.__stdout__

        output = captured_output.getvalue().strip()
        self.assertTrue(output.startswith("| TELEMETRY |"))
        json_str = output.replace("| TELEMETRY | ", "")
        data = json.loads(json_str)

        self.assertEqual(data["chain_name"], "test_chain")
        self.assertEqual(data["step"], "test_step")
        self.assertEqual(data["outcome"], "success")
        self.assertEqual(data["correlation_id"], "test_id")
        self.assertIn("timestamp", data)

if __name__ == '__main__':
    unittest.main()
