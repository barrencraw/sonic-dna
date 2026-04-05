import unittest
import json
import os
import io
from contextlib import redirect_stdout
from utils.dna_calculator import DNACalculator, ParsedDNA
from utils.dna_ui import Outcome, log_observability, dna_batch_chain

class TestSignal(unittest.TestCase):
    def test_parsed_dna_dto(self):
        """Verify DNACalculator.parse returns a ParsedDNA DTO."""
        calc = DNACalculator()
        # VOL prefix should be in rules
        # VOL (3) + amp (4) + lr (3) + sur (2) + head (2) = 14 chars
        dna = "VOL05000500512"
        result = calc.parse(dna)
        self.assertIsInstance(result, ParsedDNA)
        self.assertEqual(result.dna, dna)
        self.assertEqual(result.rule, "Volume")
        self.assertIn("amp", result.values)

    def test_log_observability_structure(self):
        """Verify log_observability outputs correctly structured JSON."""
        f = io.StringIO()
        with redirect_stdout(f):
            log_observability(
                correlation_id="test-id",
                step="TEST_STEP",
                outcome=Outcome.SUCCESS,
                latency_ms=100,
                actor_id="test-actor",
                idempotency_key="test-key"
            )
        output = f.getvalue().strip()
        self.assertTrue(output.startswith("[OBSERVABILITY]"))

        json_part = output.replace("[OBSERVABILITY] ", "")
        data = json.loads(json_part)

        self.assertEqual(data["correlation_id"], "test-id")
        self.assertEqual(data["chain_name"], "dna_batch_chain")
        self.assertEqual(data["step"], "TEST_STEP")
        self.assertEqual(data["outcome"], "success")
        self.assertEqual(data["latency_ms"], 100)
        self.assertEqual(data["actor_id"], "test-actor")
        self.assertEqual(data["idempotency_key"], "test-key")
        self.assertIn("timestamp", data)

    def test_outcome_enum_usage(self):
        """Verify Outcome enum members."""
        self.assertEqual(Outcome.SUCCESS.value, "success")
        self.assertEqual(Outcome.ERROR.value, "error")
        self.assertEqual(Outcome.SKIPPED.value, "skipped")

if __name__ == "__main__":
    unittest.main()
