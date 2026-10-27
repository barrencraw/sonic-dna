import unittest
import os
import json
import io
import sys
from utils.dna_calculator import DNACalculator
from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    InputReadError,
    PersistenceError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError,
    run_batch
)

class TestMaintainability(unittest.TestCase):
    def test_dna_status_values(self):
        """Verify explicit terminal status values for DNAStatus enum."""
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")
        self.assertEqual(DNAStatus.REFUSED, "refused")

    def test_exception_hierarchy(self):
        """Verify typed exception hierarchy relationships."""
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))

    def test_naming_alignment_and_structured_logs(self):
        """Verify canonical dna_sequence naming and JSON structured log fields."""
        calc = DNACalculator(rules_folder="rules")
        # Ensure parse parameter signature accepts dna_sequence
        res = calc.parse(dna_sequence="VOL08900750712")
        self.assertEqual(res['rule'], 'Volume')

        # Capture structured log output during run_batch execution
        captured_stdout = io.StringIO()
        sys.stdout = captured_stdout
        try:
            run_batch(correlation_id="test-corr-123", actor_id="test_runner")
        finally:
            sys.stdout = sys.__stdout__

        log_lines = [
            line for line in captured_stdout.getvalue().splitlines()
            if line.startswith("JSON_LOG:")
        ]
        self.assertGreater(len(log_lines), 0)

        first_log = json.loads(log_lines[0].replace("JSON_LOG:", "").strip())
        required_keys = {
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        }
        self.assertTrue(required_keys.issubset(set(first_log.keys())))
        self.assertEqual(first_log["correlation_id"], "test-corr-123")
        self.assertEqual(first_log["actor_id"], "test_runner")

if __name__ == '__main__':
    unittest.main()
