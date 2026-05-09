import unittest
from unittest.mock import patch
import io
import json
import os
from utils.dna_calculator import DNACalculator, ParsedDNA
from utils.dna_ui import Outcome, log_observability

class TestMaintainability(unittest.TestCase):
    def test_parsed_dna_dto(self):
        """Verify that ParsedDNA is a dataclass with expected fields."""
        parsed = ParsedDNA(dna="TEST", rule="TestRule", values={"a": 1})
        self.assertEqual(parsed.dna, "TEST")
        self.assertEqual(parsed.rule, "TestRule")
        self.assertEqual(parsed.values, {"a": 1})

    def test_calculator_returns_dto(self):
        """Verify that DNACalculator.parse returns a ParsedDNA DTO."""
        # Use a real rule if available, or mock
        project_root = os.getcwd()
        rules_folder = os.path.join(project_root, 'rules')
        if os.path.isdir(rules_folder) and os.listdir(rules_folder):
            calc = DNACalculator(rules_folder=rules_folder)
            # Find a valid prefix
            prefix = list(calc.rules.keys())[0]
            # Build a minimal valid DNA string for that prefix
            # This is a bit tricky without knowing the rule schema perfectly,
            # but we can try to just verify the return type if we can get a successful parse.
            # Alternatively, mock Rule.parse
            with patch('utils.dna_calculator.Rule.parse') as mock_parse:
                mock_parse.return_value = ParsedDNA(dna="MOCK", rule="MockRule", values={})
                result = calc.parse(prefix + "...")
                self.assertIsInstance(result, ParsedDNA)
        else:
            self.skipTest("Rules folder not found or empty")

    def test_outcome_enum(self):
        """Verify Outcome enum consistency."""
        self.assertEqual(Outcome.SUCCESS.value, "success")
        self.assertEqual(Outcome.ERROR.value, "error")
        self.assertEqual(Outcome.SKIPPED.value, "skipped")

    def test_log_observability_format(self):
        """Verify that log_observability produces the expected structured log."""
        with patch('sys.stdout', new=io.StringIO()) as fake_out:
            log_observability(
                step="TestStep",
                outcome=Outcome.SUCCESS,
                correlation_id="test-uuid",
                latency_ms=123,
                data={"key": "val"}
            )
            output = fake_out.getvalue().strip()
            self.assertTrue(output.startswith("| TELEMETRY | "))

            log_json = output.replace("| TELEMETRY | ", "")
            data = json.loads(log_json)

            self.assertEqual(data["step"], "TestStep")
            self.assertEqual(data["outcome"], "SUCCESS")
            self.assertEqual(data["correlation_id"], "test-uuid")
            self.assertEqual(data["latency_ms"], 123)
            self.assertEqual(data["data"], {"key": "val"})
            self.assertIn("timestamp", data)
            self.assertIn("chain_name", data)

if __name__ == '__main__':
    unittest.main()
