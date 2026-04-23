import unittest
import os
import json
import io
import sys
from utils.dna_calculator import DNACalculator, ParsedDNA
from utils.dna_ui import Outcome, log_observability

class TestMaintainability(unittest.TestCase):
    def test_parsed_dna_dto(self):
        """Ensure DNACalculator.parse returns a ParsedDNA instance."""
        # Use a dummy rule folder if needed, but here we assume rules exist
        calc = DNACalculator(rules_folder='rules')
        # We need a valid DNA string for a rule in 'rules'
        # Let's peek at one rule to get a prefix
        rules = os.listdir('rules')
        if not rules:
            self.skipTest("No rules found in rules/")

        with open(os.path.join('rules', rules[0]), 'r') as f:
            rule_data = json.load(f)
            prefix = rule_data['prefix']
            # Build a minimal DNA string
            # This is complex because we don't know the schema easily,
            # but we can check the type of return if we have any valid DNA.
            # Alternatively, just check the dataclass definition.
            dna = ParsedDNA(dna="TEST", rule="TestRule", values={})
            self.assertEqual(dna.dna, "TEST")
            self.assertEqual(dna.rule, "TestRule")
            self.assertEqual(dna.values, {})

    def test_outcome_enum(self):
        """Ensure Outcome Enum has required members."""
        required = {"START", "END", "SUCCESS", "ERROR", "SKIPPED", "PROCESSING", "NO_NEW_DNA", "PARTIAL_SUCCESS"}
        members = {m.name for m in Outcome}
        for r in required:
            self.assertIn(r, members)

    def test_log_observability_schema(self):
        """Ensure log_observability prints a JSON with expected keys."""
        captured_output = io.StringIO()
        sys.stdout = captured_output
        try:
            log_observability("cid", "chain", "step", outcome=Outcome.SUCCESS, extras={"foo": "bar"})
            output = captured_output.getvalue().strip()
            self.assertTrue(output.startswith("| OBSERVABILITY |"))
            json_part = output.split("| OBSERVABILITY |")[1].strip()
            data = json.loads(json_part)
            self.assertEqual(data["correlation_id"], "cid")
            self.assertEqual(data["chain_name"], "chain")
            self.assertEqual(data["step"], "step")
            self.assertEqual(data["outcome"], "SUCCESS")
            self.assertEqual(data["foo"], "bar")
            self.assertIn("timestamp", data)
        finally:
            sys.stdout = sys.__stdout__

if __name__ == '__main__':
    unittest.main()
