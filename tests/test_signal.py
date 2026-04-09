import unittest
import json
import io
import contextlib
from utils.dna_calculator import DNACalculator, ParsedDNA
from utils.dna_ui import log_observability, Outcome

class TestSignal(unittest.TestCase):
    def test_parsed_dna_structure(self):
        """Verify DNACalculator.parse returns a ParsedDNA dataclass."""
        calculator = DNACalculator(rules_folder='rules')
        # Use a known prefix, e.g., VOL for Volume
        dna = "VOL08900750712"
        result = calculator.parse(dna)

        self.assertIsInstance(result, ParsedDNA)
        self.assertEqual(result.dna, dna)
        self.assertEqual(result.rule, "Volume")
        self.assertIsInstance(result.values, dict)

    def test_log_observability_schema(self):
        """Verify log_observability outputs structured JSON with required keys."""
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            log_observability(
                correlation_id="test-id",
                chain_name="test-chain",
                step="test-step",
                outcome=Outcome.SUCCESS,
                latency_ms=100,
                idempotency_key="test-key"
            )

        output = f.getvalue().strip()
        self.assertTrue(output.startswith("[OBSERVABILITY] "))

        json_str = output[len("[OBSERVABILITY] "):]
        log_data = json.loads(json_str)

        required_keys = {
            "correlation_id", "chain_name", "step", "outcome",
            "timestamp", "actor_id", "latency_ms", "idempotency_key"
        }
        for key in required_keys:
            self.assertIn(key, log_data, f"Missing required key: {key}")

        self.assertEqual(log_data["correlation_id"], "test-id")
        self.assertEqual(log_data["outcome"], "SUCCESS")

if __name__ == '__main__':
    unittest.main()
