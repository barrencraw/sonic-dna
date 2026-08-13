import os
import sys
import json
import unittest
from unittest.mock import patch, MagicMock

# Mock GUI dependencies before any imports to prevent PySide6 headless errors
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

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
)

class TestMaintainability(unittest.TestCase):
    def test_exception_taxonomy(self):
        """Verify the custom exception classes hierarchy."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_dna_status_enum(self):
        """Verify the DNAStatus contains correct lowercase values."""
        self.assertEqual(DNAStatus.SUCCESS, 'success')
        self.assertEqual(DNAStatus.ERROR, 'error')
        self.assertEqual(DNAStatus.SKIPPED, 'skipped')
        self.assertEqual(DNAStatus.REFUSED, 'refused')

    def test_structured_logging_format(self):
        """Verify that log_structured outputs valid JSON log format."""
        with patch('sys.stdout.write') as mock_write:
            log_structured(
                correlation_id="test-corr-id",
                chain_name="test-chain",
                step="test-step",
                outcome=DNAStatus.SUCCESS,
                latency_ms=123,
                actor_id="test-actor",
                idempotency_key="test-key",
                outcome_detail="test-detail"
            )

            # Extract written text
            written_lines = [call.args[0] for call in mock_write.call_args_list if call.args]
            full_output = "".join(written_lines).strip()

            self.assertTrue(full_output.startswith("JSON_LOG:"))
            json_str = full_output.split("JSON_LOG:")[1]
            log_data = json.loads(json_str)

            # Verify mandatory fields are present
            required_fields = {
                'timestamp', 'correlation_id', 'actor_id', 'chain_name',
                'step', 'outcome', 'latency_ms', 'idempotency_key', 'outcome_detail'
            }
            for field in required_fields:
                self.assertIn(field, log_data)

            self.assertEqual(log_data['correlation_id'], "test-corr-id")
            self.assertEqual(log_data['chain_name'], "test-chain")
            self.assertEqual(log_data['step'], "test-step")
            self.assertEqual(log_data['outcome'], "success")
            self.assertEqual(log_data['latency_ms'], 123)
            self.assertEqual(log_data['actor_id'], "test-actor")
            self.assertEqual(log_data['idempotency_key'], "test-key")
            self.assertEqual(log_data['outcome_detail'], "test-detail")

if __name__ == '__main__':
    unittest.main()
