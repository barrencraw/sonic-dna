import unittest
import json
import io
import contextlib
from utils.dna_calculator import ParsedDNA, DNACalculator
from utils.dna_ui import Outcome, log_observability

class TestSignal(unittest.TestCase):
    def test_parsed_dna_dto(self):
        """Verify the ParsedDNA dataclass structure."""
        dna_str = "VOL08900750712"
        rule = "Volume"
        values = {"amp": 890, "pan": 750, "gate": 712}

        dto = ParsedDNA(dna=dna_str, rule=rule, values=values)

        self.assertEqual(dto.dna, dna_str)
        self.assertEqual(dto.rule, rule)
        self.assertEqual(dto.values, values)

    def test_log_observability_schema(self):
        """Verify that log_observability produces logs with the required schema."""
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            log_observability(
                correlation_id="test-id",
                chain_name="test-chain",
                step="test-step",
                outcome=Outcome.SUCCESS,
                latency_ms=100,
                idempotency_key="test-key"
            )

        log_line = output.getvalue().strip()
        self.assertTrue(log_line.startswith("[OBSERVABILITY] "))

        log_data = json.loads(log_line.replace("[OBSERVABILITY] ", ""))
        required_keys = {
            "timestamp", "correlation_id", "chain_name", "step",
            "outcome", "latency_ms", "actor_id", "idempotency_key"
        }
        self.assertTrue(required_keys.issubset(log_data.keys()))
        self.assertEqual(log_data["outcome"], "SUCCESS")
        self.assertEqual(log_data["chain_name"], "test-chain")

if __name__ == '__main__':
    unittest.main()
