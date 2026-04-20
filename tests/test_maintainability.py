import unittest
from utils.dna_calculator import ParsedDNA
from utils.dna_ui import Outcome, log_observability
import json
import io
from contextlib import redirect_stdout

class TestMaintainability(unittest.TestCase):
    def test_parsed_dna_structure(self):
        """Verify ParsedDNA dataclass has required fields."""
        dna = "VOL08900750712"
        rule = "Volume"
        values = {"amplitude": 89, "decay": 75, "sustain": 712}
        parsed = ParsedDNA(dna=dna, rule=rule, values=values)
        self.assertEqual(parsed.dna, dna)
        self.assertEqual(parsed.rule, rule)
        self.assertEqual(parsed.values, values)

    def test_outcome_enum_members(self):
        """Verify Outcome Enum has required members."""
        expected_members = {
            "START", "END", "SUCCESS", "ERROR", "SKIPPED",
            "PROCESSING", "NO_NEW_DNA", "PARTIAL_SUCCESS"
        }
        actual_members = {m.name for m in Outcome}
        for member in expected_members:
            self.assertIn(member, actual_members)

    def test_log_observability_schema(self):
        """Verify log_observability output matches required schema."""
        f = io.StringIO()
        with redirect_stdout(f):
            log_observability(
                chain_name="test_chain",
                step="test_step",
                outcome=Outcome.SUCCESS,
                latency_ms=100,
                idempotency_key="test_key",
                correlation_id="test_cid"
            )
        output = f.getvalue().strip()
        log_entry = json.loads(output)

        required_keys = {
            "timestamp", "correlation_id", "chain_name", "step",
            "outcome", "latency_ms", "actor_id", "idempotency_key"
        }
        for key in required_keys:
            self.assertIn(key, log_entry)

        self.assertEqual(log_entry["chain_name"], "test_chain")
        self.assertEqual(log_entry["step"], "test_step")
        self.assertEqual(log_entry["outcome"], "SUCCESS")
        self.assertEqual(log_entry["latency_ms"], 100)
        self.assertEqual(log_entry["idempotency_key"], "test_key")
        self.assertEqual(log_entry["correlation_id"], "test_cid")

if __name__ == "__main__":
    unittest.main()
