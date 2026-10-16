import unittest
import inspect
import json
from unittest.mock import patch, MagicMock
from utils.dna_calculator import DNACalculator
from utils.dna_ui import DNAStatus, log_structured, InputReadError, RuleLoadError, PersistenceError

class TestMaintainability(unittest.TestCase):
    def test_naming_alignment_dna_sequence(self):
        """Verify DNACalculator.parse parameter is explicitly named dna_sequence."""
        sig = inspect.signature(DNACalculator.parse)
        params = list(sig.parameters.keys())
        self.assertIn("dna_sequence", params, "DNACalculator.parse must use parameter name 'dna_sequence'")

        docstring = DNACalculator.parse.__doc__ or ""
        self.assertIn("dna_sequence", docstring.lower(), "Docstring must reference 'dna_sequence'")

    def test_explicit_terminal_states_enum(self):
        """Verify DNAStatus enum values and consistency."""
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")

    def test_structured_logging_keys(self):
        """Verify log_structured emits mandatory observability schema keys."""
        with patch("builtins.print") as mock_print:
            entry = log_structured(
                step="test_step",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=12.34,
                idempotency_key="VOL123",
                outcome_detail="Test outcome",
                correlation_id="test-corr-id",
                actor_id="test_actor"
            )

            mock_print.assert_called_once()
            printed_arg = mock_print.call_args[0][0]
            self.assertTrue(printed_arg.startswith("JSON_LOG:"))

            raw_json = printed_arg[len("JSON_LOG:"):]
            parsed = json.loads(raw_json)

            required_keys = {
                "timestamp", "correlation_id", "actor_id", "chain_name",
                "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
            }
            self.assertTrue(required_keys.issubset(set(parsed.keys())))
            self.assertEqual(parsed["chain_name"], "dna_batch_parsing")
            self.assertEqual(parsed["correlation_id"], "test-corr-id")
            self.assertEqual(parsed["actor_id"], "test_actor")

if __name__ == '__main__':
    unittest.main()
