import unittest
import inspect
import json
import os
import shutil
import tempfile
import sys
from unittest.mock import MagicMock

# Mock dependencies before PySide / audio imports
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

from utils.dna_calculator import DNACalculator, Rule
from utils.dna_ui import (
    main as run_batch,
    DNAProcessingError,
    RuleLoadError,
    PersistenceError,
    LedgerLoadError,
    log_structured
)

class TestMaintainabilityAndSignal(unittest.TestCase):

    def test_naming_alignment_dna_sequence_parameter(self):
        """Verify canonical parameter name 'dna_sequence' on parse methods."""
        calc_sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', calc_sig.parameters, "DNACalculator.parse must use parameter name 'dna_sequence'")

        rule_sig = inspect.signature(Rule.parse)
        self.assertIn('dna_sequence', rule_sig.parameters, "Rule.parse must use parameter name 'dna_sequence'")

    def test_structured_log_field_schema(self):
        """Verify structured log output format and mandatory keys."""
        from io import StringIO
        captured_output = StringIO()
        sys.stdout = captured_output

        try:
            log_structured(
                chain_name="dna_batch_processing",
                step="test_step",
                outcome="success",
                latency_ms=12.34,
                correlation_id="test-corr-123",
                actor_id="test_actor",
                idempotency_key="VOL08900750712",
                outcome_detail="test_detail"
            )
        finally:
            sys.stdout = sys.__stdout__

        output = captured_output.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "))

        json_str = output[len("JSON_LOG: "):]
        data = json.loads(json_str)

        required_keys = [
            "timestamp", "correlation_id", "actor_id",
            "chain_name", "step", "outcome", "latency_ms", "idempotency_key"
        ]
        for key in required_keys:
            self.assertIn(key, data, f"Structured log must contain key '{key}'")

        self.assertEqual(data["correlation_id"], "test-corr-123")
        self.assertEqual(data["actor_id"], "test_actor")
        self.assertEqual(data["chain_name"], "dna_batch_processing")
        self.assertEqual(data["step"], "test_step")
        self.assertEqual(data["outcome"], "success")
        self.assertEqual(data["latency_ms"], 12.34)
        self.assertEqual(data["idempotency_key"], "VOL08900750712")

    def test_typed_exception_hierarchy(self):
        """Verify typed exceptions inherit from base DNAProcessingError."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))

if __name__ == '__main__':
    unittest.main()
