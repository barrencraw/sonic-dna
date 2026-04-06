import unittest
import json
import io
from contextlib import redirect_stdout
from utils.dna_calculator import DNACalculator, ParsedDNA
from utils.dna_ui import log_observability, Outcome

class TestSignal(unittest.TestCase):
    def test_parsed_dna_dto(self):
        # Verify ParsedDNA DTO is returned by DNACalculator.parse
        calc = DNACalculator(rules_folder='rules')
        dna = "VOL08900750712"
        result = calc.parse(dna)
        self.assertIsInstance(result, ParsedDNA)
        self.assertEqual(result.dna, dna)
        self.assertEqual(result.rule, "Volume")
        self.assertIsInstance(result.values, dict)

    def test_log_observability_structure(self):
        # Capture stdout to verify log structure
        f = io.StringIO()
        with redirect_stdout(f):
            log_observability(
                correlation_id="test-corr-id",
                step="TEST_STEP",
                outcome=Outcome.SUCCESS.value,
                latency_ms=100,
                actor_id="test-actor",
                idempotency_key="test-key"
            )

        output = f.getvalue().strip()
        self.assertTrue(output.startswith("[OBSERVABILITY]"))

        # Parse the JSON part
        json_str = output.replace("[OBSERVABILITY] ", "")
        log_data = json.loads(json_str)

        required_fields = [
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key"
        ]
        for field in required_fields:
            self.assertIn(field, log_data)

        self.assertEqual(log_data["correlation_id"], "test-corr-id")
        self.assertEqual(log_data["step"], "TEST_STEP")
        self.assertEqual(log_data["outcome"], "success")
        self.assertEqual(log_data["latency_ms"], 100)
        self.assertEqual(log_data["actor_id"], "test-actor")
        self.assertEqual(log_data["idempotency_key"], "test-key")
        self.assertEqual(log_data["chain_name"], "dna_batch_chain")

if __name__ == '__main__':
    unittest.main()
