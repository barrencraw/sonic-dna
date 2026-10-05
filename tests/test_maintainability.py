import unittest
import inspect
import json
import tempfile
import os
from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    PersistenceError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError,
    InputReadError,
    RuleLoadError,
    log_structured,
    load_ledger
)
from utils.dna_calculator import Rule, DNACalculator

class TestMaintainabilityAndSignal(unittest.TestCase):
    def test_structured_log_keys(self):
        """Verify that log_structured includes all canonical telemetry fields."""
        log_entry = log_structured(
            correlation_id="test-corr-id",
            actor_id="test-actor",
            chain_name="test-chain",
            step="test-step",
            outcome="success",
            latency_ms=12.34,
            idempotency_key="VOL100",
            outcome_detail="detail-message"
        )
        required_keys = {
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        }
        self.assertTrue(required_keys.issubset(log_entry.keys()))
        self.assertEqual(log_entry["correlation_id"], "test-corr-id")
        self.assertEqual(log_entry["actor_id"], "test-actor")
        self.assertEqual(log_entry["chain_name"], "test-chain")

    def test_dnastatus_enum_properties(self):
        """Verify DNAStatus lowercase values for backward compatibility."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_exception_taxonomy(self):
        """Verify exception hierarchy."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_ledger_load_error_on_corrupted_file(self):
        """Verify load_ledger raises LedgerLoadError when JSON is invalid."""
        with tempfile.NamedTemporaryFile('w', delete=False) as f:
            f.write("{invalid_json:")
            temp_path = f.name

        try:
            with self.assertRaises(LedgerLoadError):
                load_ledger(temp_path)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_naming_alignment_dna_sequence(self):
        """Verify that method signature in Rule and DNACalculator uses 'dna_sequence'."""
        rule_sig = inspect.signature(Rule.parse)
        self.assertIn("dna_sequence", rule_sig.parameters)

        calc_sig = inspect.signature(DNACalculator.parse)
        self.assertIn("dna_sequence", calc_sig.parameters)

if __name__ == '__main__':
    unittest.main()
