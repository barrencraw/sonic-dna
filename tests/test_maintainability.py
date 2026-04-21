import unittest
import json
import io
from contextlib import redirect_stdout
from utils.dna_calculator import ParsedDNA
from utils.dna_ui import Outcome, log_observability

class TestMaintainability(unittest.TestCase):
    def test_parsed_dna_dto(self):
        dto = ParsedDNA(dna="VOL123", rule="Volume", values={"amp": 123})
        self.assertEqual(dto.dna, "VOL123")
        self.assertEqual(dto.rule, "Volume")
        self.assertEqual(dto.values, {"amp": 123})

    def test_outcome_enum(self):
        self.assertEqual(Outcome.SUCCESS.value, "SUCCESS")
        self.assertEqual(Outcome.ERROR.value, "ERROR")
        self.assertEqual(Outcome.SKIPPED.value, "SKIPPED")
        self.assertEqual(Outcome.START.value, "START")
        self.assertEqual(Outcome.END.value, "END")
        self.assertEqual(Outcome.PROCESSING.value, "PROCESSING")

    def test_log_observability_schema(self):
        f = io.StringIO()
        with redirect_stdout(f):
            log_observability(
                chain_name="test_chain",
                step="test_step",
                outcome=Outcome.SUCCESS,
                correlation_id="test_corr",
                idempotency_key="test_key",
                latency_ms=100,
                extra={"foo": "bar"}
            )

        log_output = f.getvalue().strip()
        entry = json.loads(log_output)

        self.assertEqual(entry["chain_name"], "test_chain")
        self.assertEqual(entry["step"], "test_step")
        self.assertEqual(entry["outcome"], "SUCCESS")
        self.assertEqual(entry["correlation_id"], "test_corr")
        self.assertEqual(entry["idempotency_key"], "test_key")
        self.assertEqual(entry["latency_ms"], 100)
        self.assertEqual(entry["foo"], "bar")
        self.assertIn("timestamp", entry)
        self.assertIn("actor_id", entry)

if __name__ == '__main__':
    unittest.main()
