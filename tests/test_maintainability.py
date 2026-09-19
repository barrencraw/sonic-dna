import os
import sys
import json
import inspect
import unittest
import tempfile
import shutil
from unittest.mock import patch, MagicMock

# Mock PySide6 and audio packages if missing
sys.modules["PySide6"] = MagicMock()
sys.modules["PySide6.QtWidgets"] = MagicMock()
sys.modules["PySide6.QtCore"] = MagicMock()
sys.modules["PySide6.QtGui"] = MagicMock()
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

from utils.dna_calculator import Rule, DNACalculator
from utils.dna_ui import (
    run_batch,
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
    def test_naming_alignment_canonical_parameters(self):
        """Verify that parse functions enforce canonical 'dna_sequence' parameter name."""
        rule_sig = inspect.signature(Rule.parse)
        self.assertIn("dna_sequence", rule_sig.parameters, "Rule.parse must use canonical 'dna_sequence' parameter")

        calc_sig = inspect.signature(DNACalculator.parse)
        self.assertIn("dna_sequence", calc_sig.parameters, "DNACalculator.parse must use canonical 'dna_sequence' parameter")

    def test_typed_error_hierarchy(self):
        """Verify that error classes inherit from appropriate base exceptions."""
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))

    def test_dna_status_enum_values(self):
        """Verify explicit terminal state constants."""
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")
        self.assertEqual(DNAStatus.REFUSED, "refused")

    def test_structured_log_keys_presence(self):
        """Verify that log_structured emits JSON logs containing all required keys."""
        required_keys = {
            "timestamp",
            "correlation_id",
            "chain_name",
            "step",
            "outcome",
            "latency_ms",
            "actor_id",
            "idempotency_key"
        }

        captured_output = []
        def mock_print(*args, **kwargs):
            captured_output.append(" ".join(map(str, args)))

        with patch("builtins.print", side_effect=mock_print):
            log_structured(
                correlation_id="test-corr-123",
                chain_name="dna_batch_parsing",
                step="test_step",
                outcome=DNAStatus.SUCCESS,
                latency_ms=12.34,
                actor_id="test_runner",
                idempotency_key="VOL100"
            )

        self.assertEqual(len(captured_output), 1)
        log_line = captured_output[0]
        self.assertTrue(log_line.startswith("JSON_LOG: "))

        json_str = log_line.replace("JSON_LOG: ", "")
        payload = json.loads(json_str)

        for key in required_keys:
            self.assertIn(key, payload, f"Structured log payload missing key: {key}")

        self.assertEqual(payload["correlation_id"], "test-corr-123")
        self.assertEqual(payload["chain_name"], "dna_batch_parsing")
        self.assertEqual(payload["actor_id"], "test_runner")
        self.assertEqual(payload["idempotency_key"], "VOL100")

    def test_ledger_corrupt_raises_typed_error(self):
        """Verify that loading a corrupted ledger raises LedgerLoadError."""
        test_dir = tempfile.mkdtemp()
        try:
            corrupt_ledger = os.path.join(test_dir, "processed_ledger.json")
            with open(corrupt_ledger, "w") as f:
                f.write("INVALID_JSON{")

            from utils.dna_ui import load_ledger
            with self.assertRaises(LedgerLoadError):
                load_ledger(corrupt_ledger)
        finally:
            shutil.rmtree(test_dir)

if __name__ == "__main__":
    unittest.main()
