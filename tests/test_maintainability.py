import unittest
import os
import json
import io
from contextlib import redirect_stdout
from utils.dna_calculator import DNACalculator, ParsedDNA
from utils.dna_ui import Outcome, log_observability

class TestMaintainability(unittest.TestCase):
    def test_parsed_dna_dataclass(self):
        # Verify DNACalculator returns ParsedDNA instance
        project_root = os.getcwd()
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
        dna = "VOL08900750712"
        result = calculator.parse(dna)

        self.assertIsInstance(result, ParsedDNA)
        self.assertEqual(result.dna, dna)
        self.assertEqual(result.rule, "Volume")
        self.assertIn('amp', result.values)

    def test_outcome_enum(self):
        # Verify Outcome Enum members
        expected_members = {
            "START", "END", "SUCCESS", "ERROR",
            "SKIPPED", "PROCESSING", "NO_NEW_DNA"
        }
        actual_members = {m.name for m in Outcome}
        self.assertTrue(expected_members.issubset(actual_members))

    def test_log_observability_format(self):
        # Verify log_observability output format
        f = io.StringIO()
        with redirect_stdout(f):
            log_observability(
                chain_name="test_chain",
                step="test_step",
                outcome=Outcome.SUCCESS,
                correlation_id="test-uuid",
                idempotency_key="test-key"
            )

        output = f.getvalue().strip()
        self.assertTrue(output.startswith("[OBSERVABILITY]"))

        json_str = output.replace("[OBSERVABILITY] ", "")
        log_data = json.loads(json_str)

        self.assertEqual(log_data["chain_name"], "test_chain")
        self.assertEqual(log_data["step"], "test_step")
        self.assertEqual(log_data["outcome"], "SUCCESS")
        self.assertEqual(log_data["correlation_id"], "test-uuid")
        self.assertEqual(log_data["idempotency_key"], "test-key")
        self.assertIn("timestamp", log_data)
        self.assertIn("actor_id", log_data)

if __name__ == '__main__':
    unittest.main()
