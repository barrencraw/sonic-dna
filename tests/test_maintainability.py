import unittest
import os
import json
import inspect
from io import StringIO
from unittest.mock import patch

from utils.dna_calculator import DNACalculator, Rule
from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    InputReadError,
    RuleLoadError,
    PersistenceError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError,
    log_structured
)

class TestMaintainability(unittest.TestCase):
    def test_naming_alignment(self):
        """Verify canonical parameter name dna_sequence across DNACalculator and Rule."""
        rule_sig = inspect.signature(Rule.parse)
        self.assertIn('dna_sequence', rule_sig.parameters, "Rule.parse must use 'dna_sequence' parameter")

        calc_sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', calc_sig.parameters, "DNACalculator.parse must use 'dna_sequence' parameter")

    def test_error_classification_hierarchy(self):
        """Verify typed error inheritance under DNAProcessingError and PersistenceError."""
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))

        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

        self.assertTrue(issubclass(LedgerLoadError, DNAProcessingError))
        self.assertTrue(issubclass(AtomicWriteError, DNAProcessingError))

    def test_dna_status_terminal_states(self):
        """Verify explicit lowercase terminal states in DNAStatus."""
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")
        self.assertEqual(DNAStatus.REFUSED, "refused")

    def test_structured_log_keys(self):
        """Verify structured log schema contains all mandatory observability keys."""
        with patch('sys.stdout', new=StringIO()) as mock_stdout:
            log_structured(
                correlation_id="test-corr-123",
                step="parse_sequence",
                outcome=DNAStatus.SUCCESS,
                latency_ms=12.34,
                actor_id="test_actor",
                idempotency_key="VOL100",
                outcome_detail="Parsed test"
            )
            output = mock_stdout.getvalue().strip()

        self.assertTrue(output.startswith("JSON_LOG: "))
        json_str = output[len("JSON_LOG: "):]
        payload = json.loads(json_str)

        required_keys = {
            "timestamp",
            "correlation_id",
            "chain_name",
            "step",
            "outcome",
            "latency_ms",
            "actor_id",
            "idempotency_key",
            "outcome_detail"
        }
        for key in required_keys:
            self.assertIn(key, payload, f"Missing required log key: {key}")

        self.assertEqual(payload["correlation_id"], "test-corr-123")
        self.assertEqual(payload["chain_name"], "dna_batch_parser")
        self.assertEqual(payload["step"], "parse_sequence")
        self.assertEqual(payload["outcome"], "success")
        self.assertEqual(payload["latency_ms"], 12.34)
        self.assertEqual(payload["actor_id"], "test_actor")
        self.assertEqual(payload["idempotency_key"], "VOL100")

if __name__ == '__main__':
    unittest.main()
