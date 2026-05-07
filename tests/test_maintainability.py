import unittest
import os
from utils.dna_calculator import DNACalculator, ParsedDNA
from utils.dna_ui import Outcome, log_observability

class TestMaintainability(unittest.TestCase):
    def test_dna_calculator_returns_dto(self):
        project_root = os.getcwd()
        calculator = DNACalculator(rules_folder=os.path.join(project_root, 'rules'))
        # Using a known valid DNA string from test_idempotency.py
        dna = "VOL08900750712"
        result = calculator.parse(dna)

        self.assertIsInstance(result, ParsedDNA)
        self.assertEqual(result.dna, dna)
        self.assertEqual(result.rule, "Volume")
        self.assertIsInstance(result.values, dict)

    def test_outcome_enum_values(self):
        self.assertEqual(Outcome.START.value, "START")
        self.assertEqual(Outcome.END.value, "END")
        self.assertEqual(Outcome.SUCCESS.value, "SUCCESS")
        self.assertEqual(Outcome.ERROR.value, "ERROR")
        self.assertEqual(Outcome.SKIPPED.value, "SKIPPED")

    def test_log_observability_runs(self):
        # Simply ensure it doesn't crash and outputs something
        # In a real scenario we might capture stdout
        log_observability("Test Step", Outcome.SUCCESS, correlation_id="test-id")

if __name__ == '__main__':
    unittest.main()
