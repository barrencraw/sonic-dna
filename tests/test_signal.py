#!/usr/bin/env python3
import unittest
import json
import io
import contextlib
from utils.dna_calculator import ParsedDNA, DNACalculator
from utils.dna_ui import log_observability, Outcome

class TestSignal(unittest.TestCase):
    def test_parsed_dna_structure(self):
        # Assert ParsedDNA structure (naming alignment)
        pd = ParsedDNA(dna="VOL0890", rule="Volume", values={"amp": 890})
        self.assertEqual(pd.dna, "VOL0890")
        self.assertEqual(pd.rule, "Volume")
        self.assertEqual(pd.values["amp"], 890)

    def test_log_observability_schema(self):
        # Assert log_observability output schema (observability hygiene)
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            log_observability(
                correlation_id="test-corr-id",
                step="test_step",
                outcome=Outcome.SUCCESS,
                latency_ms=123,
                actor_id="test-actor",
                idempotency_key="test-key"
            )

        output = f.getvalue().strip()
        self.assertTrue(output.startswith("[OBSERVABILITY]"))

        log_json_str = output.replace("[OBSERVABILITY] ", "")
        log_data = json.loads(log_json_str)

        required_keys = {
            "correlation_id", "chain_name", "step", "outcome",
            "latency_ms", "actor_id", "timestamp", "idempotency_key"
        }
        for key in required_keys:
            self.assertIn(key, log_data)

        self.assertEqual(log_data["correlation_id"], "test-corr-id")
        self.assertEqual(log_data["chain_name"], "dna_batch_chain")
        self.assertEqual(log_data["outcome"], "success")
        self.assertEqual(log_data["latency_ms"], 123)
        self.assertEqual(log_data["actor_id"], "test-actor")

    def test_calculator_returns_parsed_dna(self):
        # Assert calculator returns the correct DTO
        calc = DNACalculator(rules_folder='rules')
        result = calc.parse("VOL08900750712")
        self.assertIsInstance(result, ParsedDNA)
        self.assertEqual(result.rule, "Volume")

if __name__ == "__main__":
    unittest.main()
