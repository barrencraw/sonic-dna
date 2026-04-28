import unittest
import json
from io import StringIO
from unittest.mock import patch
from utils.dna_calculator import ParsedDNA
from utils.dna_ui import Outcome, log_observability

class TestMaintainability(unittest.TestCase):
    def test_parsed_dna_dataclass(self):
        """Ensure ParsedDNA has the expected fields."""
        p = ParsedDNA(dna="TEST", rule="TestRule", values={"k": "v"})
        self.assertEqual(p.dna, "TEST")
        self.assertEqual(p.rule, "TestRule")
        self.assertEqual(p.values, {"k": "v"})

    def test_outcome_enum(self):
        """Ensure Outcome enum has the required members."""
        expected = {
            "START", "END", "SUCCESS", "ERROR", "SKIPPED",
            "PROCESSING", "PARTIAL_SUCCESS", "NO_NEW_DNA"
        }
        actual = {m.name for m in Outcome}
        for name in expected:
            self.assertIn(name, actual)

    def test_log_observability_format(self):
        """Ensure log_observability outputs the correct structured format."""
        with patch('sys.stdout', new=StringIO()) as fake_out:
            log_observability(
                chain_name="test_chain",
                step="test_step",
                outcome=Outcome.SUCCESS,
                correlation_id="test_id",
                idempotency_key="test_key"
            )
            output = fake_out.getvalue().strip()

            self.assertTrue(output.startswith("| TELEMETRY | "))
            json_str = output.replace("| TELEMETRY | ", "")
            data = json.loads(json_str)

            self.assertEqual(data["chain_name"], "test_chain")
            self.assertEqual(data["step"], "test_step")
            self.assertEqual(data["outcome"], "success")
            self.assertEqual(data["correlation_id"], "test_id")
            self.assertEqual(data["idempotency_key"], "test_key")
            self.assertIn("timestamp", data)
            self.assertIn("actor_id", data)

if __name__ == '__main__':
    unittest.main()
