import unittest
import os
import io
import json
from contextlib import redirect_stdout
from utils.dna_ui import TerminalOutcome, log_structured, DNAProcessingResult

class TestMaintainability(unittest.TestCase):
    def test_terminal_outcome_enum(self):
        """Ensure TerminalOutcome Enum has the required members for canonical naming."""
        self.assertTrue(hasattr(TerminalOutcome, 'SUCCESS'))
        self.assertTrue(hasattr(TerminalOutcome, 'PARSE_ERROR'))
        self.assertTrue(hasattr(TerminalOutcome, 'SKIPPED'))
        self.assertEqual(TerminalOutcome.SUCCESS.value, "success")
        self.assertEqual(TerminalOutcome.PARSE_ERROR.value, "parse_error")
        self.assertEqual(TerminalOutcome.SKIPPED.value, "skipped")

    def test_structured_logging_format(self):
        """Verify that the structured logging includes the required fields."""
        f = io.StringIO()
        with redirect_stdout(f):
            log_structured(
                chain_name="test_chain",
                step="test_step",
                outcome="test_outcome",
                latency_ms=123.45,
                correlation_id="test_corr_id",
                idempotency_key="test_key",
                extra_field="extra_value"
            )

        log_output = f.getvalue().strip()
        log_entry = json.loads(log_output)

        required_fields = [
            'timestamp', 'correlation_id', 'chain_name', 'step', 'outcome',
            'latency_ms', 'idempotency_key'
        ]
        for field in required_fields:
            self.assertIn(field, log_entry, f"Missing required field: {field}")

        self.assertEqual(log_entry['chain_name'], "test_chain")
        self.assertEqual(log_entry['step'], "test_step")
        self.assertEqual(log_entry['outcome'], "test_outcome")
        self.assertEqual(log_entry['latency_ms'], 123.45)
        self.assertEqual(log_entry['correlation_id'], "test_corr_id")
        self.assertEqual(log_entry['idempotency_key'], "test_key")
        self.assertEqual(log_entry['extra_field'], "extra_value")

    def test_dna_processing_result_dto(self):
        """Ensure DNAProcessingResult DTO has expected attributes."""
        res = DNAProcessingResult(
            dna_sequence="DNA123",
            outcome=TerminalOutcome.SUCCESS,
            rule="Volume",
            parsed_data={"val": 1},
            error_message=None
        )
        self.assertEqual(res.dna_sequence, "DNA123")
        self.assertEqual(res.outcome, TerminalOutcome.SUCCESS)
        self.assertEqual(res.rule, "Volume")
        self.assertEqual(res.parsed_data, {"val": 1})
        self.assertIsNone(res.error_message)

if __name__ == '__main__':
    unittest.main()
