import inspect
import json
import re
import unittest
from unittest.mock import patch, MagicMock
import utils.dna_ui as dna_ui

class TestMaintainability(unittest.TestCase):
    def test_run_batch_signature(self):
        """Verify the signature of run_batch contains correlation_id and alias main exists."""
        sig = inspect.signature(dna_ui.run_batch)
        self.assertIn('correlation_id', sig.parameters)
        self.assertEqual(dna_ui.main, dna_ui.run_batch)

    def test_canonical_naming_conventions(self):
        """Verify that utils/dna_ui.py uses canonical variable names dna_sequence and dna_sequence_list."""
        with open(dna_ui.__file__, 'r', encoding='utf-8') as f:
            code = f.read()

        # Check for dna_sequence_list and dna_sequence presence
        self.assertIn('dna_sequence_list', code)
        self.assertIn('dna_sequence', code)

    def test_structured_logs_schema(self):
        """Verify that log_structured emits JSON logs with the JSON_LOG: prefix and all mandatory fields."""
        captured_logs = []

        def mock_print(msg, *args, **kwargs):
            captured_logs.append(msg)

        with patch('builtins.print', side_effect=mock_print):
            dna_ui.log_structured(
                step='parse_dna',
                outcome='success',
                latency_ms=123,
                idempotency_key='VOL12345',
                outcome_detail='Successfully parsed',
                correlation_id='test-uuid-1234',
                actor_id='test-actor'
            )

        self.assertEqual(len(captured_logs), 1)
        log_line = captured_logs[0]
        self.assertTrue(log_line.startswith("JSON_LOG:"))

        # Strip prefix and parse JSON
        json_str = log_line[len("JSON_LOG:"):]
        log_data = json.loads(json_str)

        # Check mandatory fields
        mandatory_fields = [
            'timestamp', 'correlation_id', 'actor_id', 'chain_name',
            'step', 'outcome', 'latency_ms', 'idempotency_key', 'outcome_detail'
        ]
        for field in mandatory_fields:
            self.assertIn(field, log_data)

        # Check field values
        self.assertEqual(log_data['correlation_id'], 'test-uuid-1234')
        self.assertEqual(log_data['actor_id'], 'test-actor')
        self.assertEqual(log_data['chain_name'], 'dna_batch_parsing')
        self.assertEqual(log_data['step'], 'parse_dna')
        self.assertEqual(log_data['outcome'], 'success')
        self.assertEqual(log_data['latency_ms'], 123)
        self.assertEqual(log_data['idempotency_key'], 'VOL12345')
        self.assertEqual(log_data['outcome_detail'], 'Successfully parsed')

        # Verify UTC ISO 8601 formatting of timestamp: %Y-%m-%dT%H:%M:%SZ
        timestamp_regex = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$'
        self.assertTrue(re.match(timestamp_regex, log_data['timestamp']),
                        f"Timestamp {log_data['timestamp']} does not match pattern %Y-%m-%dT%H:%M:%SZ")

if __name__ == '__main__':
    unittest.main()
