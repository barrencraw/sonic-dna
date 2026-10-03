import sys
from unittest.mock import MagicMock

# Mock GUI / heavy dependencies if needed
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6

import unittest
import inspect
import json
import io
import contextlib
from utils.dna_calculator import DNACalculator
from utils.dna_ui import (
    DNAProcessingError,
    InputReadError,
    PersistenceError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError,
    log_structured
)


class TestMaintainabilityAndSignal(unittest.TestCase):
    def test_typed_error_hierarchy(self):
        """Verify explicit typed error classification inheritance."""
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_naming_alignment(self):
        """Verify canonical naming parameter alignment for DNA sequences."""
        sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', sig.parameters, "DNACalculator.parse must use 'dna_sequence' parameter")

    def test_structured_log_schema(self):
        """Verify structured log output contains required observability keys."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            log_structured(
                correlation_id="test-corr-123",
                actor_id="test_runner",
                chain_name="dna_batch_processing",
                step="parse_sequence",
                outcome="success",
                latency_ms=12.34,
                idempotency_key="VOL100",
                outcome_detail="Parsed test sequence"
            )

        output = buf.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG:"))
        json_str = output[len("JSON_LOG:"):]
        log_data = json.loads(json_str)

        required_keys = {
            "timestamp",
            "correlation_id",
            "actor_id",
            "chain_name",
            "step",
            "outcome",
            "latency_ms",
            "idempotency_key",
            "outcome_detail"
        }
        for key in required_keys:
            self.assertIn(key, log_data)

        self.assertEqual(log_data["correlation_id"], "test-corr-123")
        self.assertEqual(log_data["actor_id"], "test_runner")
        self.assertEqual(log_data["chain_name"], "dna_batch_processing")
        self.assertEqual(log_data["step"], "parse_sequence")
        self.assertEqual(log_data["outcome"], "success")
        self.assertEqual(log_data["latency_ms"], 12.34)
        self.assertEqual(log_data["idempotency_key"], "VOL100")


if __name__ == '__main__':
    unittest.main()
