import unittest
import os
import json
from utils.dna_calculator import DNACalculator, ParsedDNA
from utils.dna_ui import Outcome

class TestMaintainability(unittest.TestCase):
    def test_parsed_dna_dto(self):
        """Verify ParsedDNA DTO structure and usage."""
        dto = ParsedDNA(dna="VOL08900750712", rule="Volume", values={"amp": 890})
        self.assertEqual(dto.dna, "VOL08900750712")
        self.assertEqual(dto.rule, "Volume")
        self.assertEqual(dto.values["amp"], 890)

    def test_outcome_enum_consistency(self):
        """Verify Outcome enum contains required canonical states."""
        required = {"START", "END", "SUCCESS", "ERROR", "SKIPPED"}
        actual = {m.name for m in Outcome}
        for state in required:
            self.assertIn(state, actual)

    def test_dna_calculator_returns_dto(self):
        """Verify DNACalculator.parse returns a ParsedDNA instance."""
        # Need a real or mock rule folder
        project_root = os.getcwd()
        rules_folder = os.path.join(project_root, 'rules')
        if not os.path.isdir(rules_folder):
            self.skipTest("Rules folder not found")

        calc = DNACalculator(rules_folder=rules_folder)
        dna = "VOL08900750712"
        result = calc.parse(dna)
        self.assertIsInstance(result, ParsedDNA)
        self.assertEqual(result.dna, dna)
        self.assertEqual(result.rule, "Volume")

if __name__ == '__main__':
    unittest.main()
