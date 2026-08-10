import sys
from unittest.mock import MagicMock, patch

# Mock dependencies before any imports to avoid import problems
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

import unittest
import json
import inspect
from utils.dna_ui import run_batch, DNAStatus, log_structured, BatchResult

class TestMaintainability(unittest.TestCase):
    def test_run_batch_signature(self):
        """Verify run_batch has correlation_id parameter."""
        sig = inspect.signature(run_batch)
        self.assertIn('correlation_id', sig.parameters)
        # Verify it defaults to None or accepts None
        param = sig.parameters['correlation_id']
        self.assertEqual(param.default, None)

    def test_dnastatus_enum_properties(self):
        """Verify DNAStatus enum has correct lowercase values."""
        self.assertEqual(DNAStatus.SUCCESS.value, 'success')
        self.assertEqual(DNAStatus.ERROR.value, 'error')
        self.assertEqual(DNAStatus.SKIPPED.value, 'skipped')
        self.assertEqual(DNAStatus.REFUSED.value, 'refused')

    def test_log_structured_schema(self):
        """Verify that log_structured emits JSON logs with the correct prefix and schema."""
        with patch('builtins.print') as mock_print:
            log_structured(
                step='test_step',
                outcome='success',
                latency_ms=123,
                correlation_id='my-corr-id',
                actor_id='user',
                chain_name='test_chain',
                idempotency_key='test_dna',
                outcome_detail='details'
            )
            mock_print.assert_called_once()
            args, kwargs = mock_print.call_args
            log_output = args[0]

            # Assert prefix
            self.assertTrue(log_output.startswith("JSON_LOG: "))

            # Parse the JSON part
            json_str = log_output[len("JSON_LOG: "):]
            log_data = json.loads(json_str)

            # Assert mandatory fields
            mandatory_fields = [
                'timestamp', 'correlation_id', 'actor_id', 'chain_name',
                'step', 'outcome', 'latency_ms', 'idempotency_key', 'outcome_detail'
            ]
            for field in mandatory_fields:
                self.assertIn(field, log_data)

            self.assertEqual(log_data['correlation_id'], 'my-corr-id')
            self.assertEqual(log_data['actor_id'], 'user')
            self.assertEqual(log_data['chain_name'], 'test_chain')
            self.assertEqual(log_data['step'], 'test_step')
            self.assertEqual(log_data['outcome'], 'success')
            self.assertEqual(log_data['latency_ms'], 123)
            self.assertEqual(log_data['idempotency_key'], 'test_dna')
            self.assertEqual(log_data['outcome_detail'], 'details')

            # Timestamp check: should end with Z (UTC) and match ISO 8601 formatting
            timestamp = log_data['timestamp']
            self.assertTrue(timestamp.endswith('Z'))
            self.assertIn('T', timestamp)

if __name__ == '__main__':
    unittest.main()
