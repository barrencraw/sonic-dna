import os
import json
import io
import unittest
from contextlib import redirect_stdout
from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    InputReadError,
    RuleLoadError,
    PersistenceError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError,
    log_structured,
    load_ledger,
    main as run_batch
)
from utils.dna_calculator import RuleParseError, DNACalculator

class TestMaintainabilityAndSignal(unittest.TestCase):
    def test_dna_status_values(self):
        """Ensure terminal statuses are explicit string enums."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_error_hierarchy(self):
        """Ensure typed error classification subclasses are maintained."""
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleParseError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_structured_log_fields(self):
        """Verify standardized structured logging fields and format."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            log_structured(
                correlation_id="test-cid-123",
                actor_id="test-actor",
                chain_name="dna_batch_parser",
                step="test_step",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=12.3456,
                idempotency_key="DNA123",
                outcome_detail="Testing detail"
            )

        output = buf.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "))
        json_payload = output[len("JSON_LOG: "):]
        data = json.loads(json_payload)

        required_fields = [
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        ]
        for field in required_fields:
            self.assertIn(field, data)

        self.assertEqual(data["correlation_id"], "test-cid-123")
        self.assertEqual(data["actor_id"], "test-actor")
        self.assertEqual(data["chain_name"], "dna_batch_parser")
        self.assertEqual(data["step"], "test_step")
        self.assertEqual(data["outcome"], "success")
        self.assertEqual(data["latency_ms"], 12.346)
        self.assertEqual(data["idempotency_key"], "DNA123")
        self.assertEqual(data["outcome_detail"], "Testing detail")

    def test_corrupted_ledger_raises_typed_error(self):
        """Verify that a corrupted ledger raises LedgerLoadError instead of silently returning empty dict."""
        import tempfile
        with tempfile.NamedTemporaryFile('w', delete=False) as f:
            f.write("{invalid json content")
            temp_path = f.name

        try:
            with self.assertRaises(LedgerLoadError):
                load_ledger(temp_path)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_dna_calculator_naming_alignment(self):
        """Verify DNACalculator parse method accepts dna_sequence argument."""
        calc = DNACalculator(rules_folder='rules')
        import inspect
        sig = inspect.signature(calc.parse)
        self.assertIn("dna_sequence", sig.parameters)

if __name__ == '__main__':
    unittest.main()
