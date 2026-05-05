import unittest
import os
import json
from utils.dna_calculator import DNACalculator, ParsedDNA
from utils.dna_ui import Outcome, log_observability
from io import StringIO
import sys

class TestMaintainability(unittest.TestCase):
    def test_parsed_dna_dto(self):
        # Ensure ParsedDNA is a dataclass and has expected fields
        dna = "VOL08900750712"
        rule = "Volume"
        values = {"amp": 890, "pan": 75, "mod": 712}
        dto = ParsedDNA(dna=dna, rule=rule, values=values)
        self.assertEqual(dto.dna, dna)
        self.assertEqual(dto.rule, rule)
        self.assertEqual(dto.values, values)

    def test_outcome_enum(self):
        # Ensure canonical outcomes exist
        self.assertEqual(Outcome.SUCCESS.name, "SUCCESS")
        self.assertEqual(Outcome.ERROR.name, "ERROR")
        self.assertEqual(Outcome.SKIPPED.name, "SKIPPED")
        self.assertEqual(Outcome.START.name, "START")
        self.assertEqual(Outcome.END.name, "END")

    def test_log_observability_schema(self):
        # Redirect stdout to capture logs
        captured_output = StringIO()
        sys.stdout = captured_output

        correlation_id = "test-id"
        log_observability(correlation_id, "Test Step", Outcome.SUCCESS, actor_id="test-actor")

        sys.stdout = sys.__stdout__
        log_line = captured_output.getvalue().strip()

        self.assertTrue(log_line.startswith("| TELEMETRY |"))
        json_str = log_line.split("| TELEMETRY |")[1].strip()
        data = json.loads(json_str)

        expected_keys = {"correlation_id", "chain_name", "step", "outcome", "latency_ms", "actor_id", "timestamp", "data"}
        self.assertTrue(expected_keys.issubset(data.keys()))
        self.assertEqual(data["correlation_id"], correlation_id)
        self.assertEqual(data["outcome"], "SUCCESS")
        self.assertEqual(data["actor_id"], "test-actor")

if __name__ == '__main__':
    unittest.main()
