import unittest
import json
import io
import sys
from utils.dna_calculator import ParsedDNA
from utils.dna_ui import Outcome, log_observability

class TestMaintainability(unittest.TestCase):
    def test_parsed_dna_dto(self):
        dto = ParsedDNA(dna="DNA", rule="RULE", values={"key": "val"})
        self.assertEqual(dto.dna, "DNA")
        self.assertEqual(dto.rule, "RULE")
        self.assertEqual(dto.values, {"key": "val"})

    def test_outcome_enum(self):
        self.assertEqual(Outcome.SUCCESS.value, "SUCCESS")
        self.assertEqual(Outcome.ERROR.value, "ERROR")
        self.assertEqual(Outcome.PROCESSING.value, "PROCESSING")

    def test_log_observability_schema(self):
        captured_output = io.StringIO()
        sys.stdout = captured_output
        try:
            log_observability(
                correlation_id="corr_123",
                chain_name="test_chain",
                step="test_step",
                outcome="test_outcome",
                idempotency_key="key_123"
            )
        finally:
            sys.stdout = sys.__stdout__

        output = captured_output.getvalue().strip()
        self.assertTrue(output.startswith("| TELEMETRY | "))

        json_part = output[len("| TELEMETRY | "):]
        payload = json.loads(json_part)

        self.assertEqual(payload["correlation_id"], "corr_123")
        self.assertEqual(payload["chain_name"], "test_chain")
        self.assertEqual(payload["step"], "test_step")
        self.assertEqual(payload["outcome"], "test_outcome")
        self.assertEqual(payload["idempotency_key"], "key_123")
        self.assertEqual(payload["actor_id"], "system")

if __name__ == '__main__':
    unittest.main()
