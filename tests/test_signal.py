import unittest
import json
import io
import contextlib
from utils.dna_calculator import ParsedDNA, DNACalculator
from utils.dna_ui import log_observability, Outcome

class TestSignal(unittest.TestCase):
    def test_parsed_dna_dto(self):
        """Verify the ParsedDNA dataclass structure."""
        dna = "VOL08900750712"
        rule = "Volume"
        values = {"amp": 890, "pan": 75, "env": 712}

        dto = ParsedDNA(dna=dna, rule=rule, values=values)

        self.assertEqual(dto.dna, dna)
        self.assertEqual(dto.rule, rule)
        self.assertEqual(dto.values, values)

    def test_log_observability_schema(self):
        """Verify the log_observability output schema."""
        step = "test_step"
        outcome = Outcome.SUCCESS
        correlation_id = "test-corr-id"
        idempotency_key = "test-dna"

        # Capture stdout
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            log_observability(
                step=step,
                outcome=outcome,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key
            )

        output = f.getvalue().strip()
        log_entry = json.loads(output)

        # Required fields
        expected_keys = {
            "timestamp", "correlation_id", "chain_name", "step",
            "outcome", "latency_ms", "actor_id", "idempotency_key"
        }
        self.assertTrue(expected_keys.issubset(log_entry.keys()))

        self.assertEqual(log_entry["step"], step)
        self.assertEqual(log_entry["outcome"], outcome.value)
        self.assertEqual(log_entry["correlation_id"], correlation_id)
        self.assertEqual(log_entry["idempotency_key"], idempotency_key)
        self.assertEqual(log_entry["chain_name"], "dna_batch_chain")

if __name__ == '__main__':
    unittest.main()
