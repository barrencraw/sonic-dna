import unittest
import inspect
import json
import io
import os
import tempfile
from unittest.mock import patch

from utils.dna_calculator import DNACalculator, Rule
from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    RuleLoadError,
    InputReadError,
    PersistenceError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError,
    log_structured,
    load_ledger
)

class TestMaintainability(unittest.TestCase):

    def test_dna_status_enum_values(self):
        """Verify DNAStatus uses lowercase string values for ledger compatibility."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_exception_taxonomy(self):
        """Verify exception hierarchy inheritance."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_naming_alignment_dna_sequence(self):
        """Verify parse methods use canonical parameter name 'dna_sequence'."""
        rule_sig = inspect.signature(Rule.parse)
        calc_sig = inspect.signature(DNACalculator.parse)

        self.assertIn('dna_sequence', rule_sig.parameters)
        self.assertIn('dna_sequence', calc_sig.parameters)

    def test_structured_log_schema(self):
        """Verify log_structured outputs valid JSON with all required fields."""
        output_buffer = io.StringIO()
        with patch('sys.stdout', new=output_buffer):
            log_structured(
                correlation_id="test-corr-id",
                chain_name="dna_batch_parser",
                step="parse_sequence",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=12.34,
                actor_id="test_actor",
                idempotency_key="VOL08900750712",
                outcome_detail="test detail"
            )

        printed_output = output_buffer.getvalue().strip()
        self.assertTrue(printed_output.startswith("JSON_LOG: "))

        json_str = printed_output[len("JSON_LOG: "):]
        log_data = json.loads(json_str)

        required_keys = [
            'timestamp',
            'correlation_id',
            'actor_id',
            'chain_name',
            'step',
            'outcome',
            'latency_ms',
            'idempotency_key',
            'outcome_detail'
        ]
        for key in required_keys:
            self.assertIn(key, log_data)

        self.assertEqual(log_data['correlation_id'], "test-corr-id")
        self.assertEqual(log_data['actor_id'], "test_actor")
        self.assertEqual(log_data['chain_name'], "dna_batch_parser")
        self.assertEqual(log_data['step'], "parse_sequence")
        self.assertEqual(log_data['outcome'], "success")
        self.assertEqual(log_data['latency_ms'], 12.34)
        self.assertEqual(log_data['idempotency_key'], "VOL08900750712")

    def test_corrupted_ledger_raises_ledger_load_error(self):
        """Verify corrupted ledger file raises typed LedgerLoadError."""
        with tempfile.NamedTemporaryFile('w', delete=False) as tmp:
            tmp.write("{ invalid json")
            tmp_path = tmp.name

        try:
            with self.assertRaises(LedgerLoadError):
                load_ledger(tmp_path)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

if __name__ == '__main__':
    unittest.main()
