import unittest
import json
import os
import io
from contextlib import redirect_stdout
from utils.dna_calculator import DNACalculator, ParsedDNA
from utils.dna_ui import Outcome

class TestMaintainability(unittest.TestCase):
    def test_parsed_dna_dto_alignment(self):
        # Verify DNACalculator.parse returns ParsedDNA instance
        rules_folder = 'rules'
        calc = DNACalculator(rules_folder=rules_folder)

        if "VOL" in calc.rules:
            result = calc.parse("VOL08900750712")
            self.assertIsInstance(result, ParsedDNA)
            self.assertEqual(result.rule, "Volume")
            self.assertEqual(result.dna, "VOL08900750712")
            self.assertIsInstance(result.values, dict)

    def test_telemetry_schema_standardization(self):
        from utils.dna_ui import log_observability

        f = io.StringIO()
        with redirect_stdout(f):
            log_observability("test_step", Outcome.SUCCESS, "test_corr_id", extra={"key": "val"})

        output = f.getvalue().strip()
        self.assertTrue(output.startswith("| TELEMETRY |"))

        json_part = output.replace("| TELEMETRY | ", "")
        data = json.loads(json_part)

        expected_keys = {"correlation_id", "chain_name", "step", "outcome", "actor_id", "timestamp", "key"}
        self.assertTrue(expected_keys.issubset(data.keys()))
        self.assertEqual(data["step"], "test_step")
        self.assertEqual(data["outcome"], "SUCCESS")
        self.assertEqual(data["correlation_id"], "test_corr_id")

if __name__ == "__main__":
    unittest.main()
