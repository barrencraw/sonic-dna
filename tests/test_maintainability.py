import unittest
import os
import json
import io
from contextlib import redirect_stdout
from utils.dna_ui import TerminalOutcome, log_structured
from utils.dna_calculator import DNACalculator
import inspect

class TestMaintainability(unittest.TestCase):
    def test_terminal_outcome_enum(self):
        """Regression guard for TerminalOutcome Enum members."""
        expected_members = {"SUCCESS", "PARSE_ERROR", "SKIPPED"}
        actual_members = {m.name for m in TerminalOutcome}
        for member in expected_members:
            self.assertIn(member, actual_members)

    def test_dna_sequence_naming_alignment(self):
        """Regression guard for canonical naming alignment (dna_sequence)."""
        # Check DNACalculator.parse parameter name
        sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', sig.parameters)

    def test_log_structured_format(self):
        """Regression guard for standardized structured logging fields."""
        f = io.StringIO()
        with redirect_stdout(f):
            log_structured(
                correlation_id="test-corr-id",
                chain_name="test-chain",
                step="test-step",
                outcome="test-outcome",
                latency_ms=123.45,
                actor_id="test-actor",
                idempotency_key="test-key"
            )

        output = f.getvalue().strip()
        log_entry = json.loads(output)

        required_fields = {
            "correlation_id", "chain_name", "step", "outcome",
            "latency_ms", "actor_id", "idempotency_key", "timestamp"
        }
        for field in required_fields:
            self.assertIn(field, log_entry)

        self.assertEqual(log_entry["correlation_id"], "test-corr-id")
        self.assertEqual(log_entry["actor_id"], "test-actor")

if __name__ == '__main__':
    unittest.main()
