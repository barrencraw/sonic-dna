import unittest
import json
import io
from contextlib import redirect_stdout
from utils.dna_calculator import ParsedDNA
from utils.dna_ui import Outcome, log_observability

class TestSignal(unittest.TestCase):
    def test_parsed_dna_dto(self):
        # Verify ParsedDNA DTO structure
        dto = ParsedDNA(dna="DNA", rule="RULE", values={"key": "val"})
        self.assertEqual(dto.dna, "DNA")
        self.assertEqual(dto.rule, "RULE")
        self.assertEqual(dto.values, {"key": "val"})

    def test_outcome_enum(self):
        # Verify Outcome Enum members
        self.assertEqual(Outcome.SUCCESS.value, "SUCCESS")
        self.assertEqual(Outcome.ERROR.value, "ERROR")
        self.assertEqual(Outcome.START.value, "START")
        self.assertEqual(Outcome.END.value, "END")

    def test_log_observability_format(self):
        # Verify structured log format
        f = io.StringIO()
        with redirect_stdout(f):
            log_observability(
                correlation_id="corr-123",
                chain_name="test_chain",
                step="test_step",
                outcome=Outcome.SUCCESS.value,
                latency_ms=100,
                actor_id="test_actor",
                idempotency_key="test_key"
            )
        output = f.getvalue().strip()
        # Format is "[TIMESTAMP] {JSON}"
        self.assertTrue(output.startswith("[20"))
        json_part = output[output.find("{"):]
        log_entry = json.loads(json_part)

        self.assertEqual(log_entry["correlation_id"], "corr-123")
        self.assertEqual(log_entry["chain_name"], "test_chain")
        self.assertEqual(log_entry["step"], "test_step")
        self.assertEqual(log_entry["outcome"], "SUCCESS")
        self.assertEqual(log_entry["latency_ms"], 100)
        self.assertEqual(log_entry["actor_id"], "test_actor")
        self.assertEqual(log_entry["idempotency_key"], "test_key")
        self.assertIn("timestamp", log_entry)

if __name__ == '__main__':
    unittest.main()
