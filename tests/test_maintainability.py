import unittest
import json
import os
import io
from contextlib import redirect_stdout
from utils.dna_calculator import DNACalculator, ParsedDNA
from utils.dna_ui import Outcome

class TestMaintainability(unittest.TestCase):
    def test_parsed_dna_dataclass(self):
        # Verify ParsedDNA exists and has correct fields
        pdna = ParsedDNA(dna="TEST", rule="Rule", values={"a": 1})
        self.assertEqual(pdna.dna, "TEST")
        self.assertEqual(pdna.rule, "Rule")
        self.assertEqual(pdna.values, {"a": 1})

    def test_dna_calculator_returns_parsed_dna(self):
        # We need a dummy rule or real rules
        calc = DNACalculator(rules_folder='rules')
        # Assuming VOL rules exist from memory
        dna = "VOL08900750712"
        result = calc.parse(dna)
        self.assertIsInstance(result, ParsedDNA)
        self.assertEqual(result.dna, dna)
        self.assertEqual(result.rule, "Volume")

    def test_outcome_enum(self):
        self.assertEqual(Outcome.SUCCESS.value, "SUCCESS")
        self.assertEqual(Outcome.ERROR.value, "ERROR")
        self.assertEqual(Outcome.START.value, "START")
        self.assertEqual(Outcome.END.value, "END")

    def test_log_observability_schema(self):
        from utils.dna_ui import log_observability
        f = io.StringIO()
        with redirect_stdout(f):
            log_observability(step="test_step", outcome="test_outcome", correlation_id="test_cid")

        output = f.getvalue().strip()
        self.assertTrue(output.startswith("| TELEMETRY | "))
        json_str = output.replace("| TELEMETRY | ", "")
        data = json.loads(json_str)

        self.assertEqual(data["step"], "test_step")
        self.assertEqual(data["outcome"], "test_outcome")
        self.assertEqual(data["correlation_id"], "test_cid")
        self.assertEqual(data["chain_name"], "dna_batch_chain")
        self.assertIn("timestamp", data)

if __name__ == '__main__':
    unittest.main()
