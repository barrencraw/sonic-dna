import unittest
import inspect
import sys
import os
import json
import io
import re
from unittest.mock import patch
import utils.dna_ui as dna_ui

class TestMaintainability(unittest.TestCase):
    def test_run_batch_signature(self):
        """Verify run_batch has correlation_id parameter in its signature."""
        sig = inspect.signature(dna_ui.run_batch)
        self.assertIn('correlation_id', sig.parameters)

    def test_log_structured_mandatory_fields(self):
        """Verify log_structured prints JSON logs with the JSON_LOG: prefix and all mandatory fields."""
        # Capture standard output
        captured_output = io.StringIO()
        with patch('sys.stdout', new=captured_output):
            dna_ui.log_structured(
                step="test_step",
                outcome="success",
                correlation_id="test_corr_123",
                actor_id="test_actor",
                chain_name="test_chain",
                latency_ms=42,
                idempotency_key="test_key_123",
                outcome_detail="test detail"
            )

        output = captured_output.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG:"))

        # Parse JSON
        json_part = output[len("JSON_LOG:"):]
        log_data = json.loads(json_part)

        # Check mandatory fields: timestamp (UTC), correlation_id, actor_id, chain_name, step, outcome, latency_ms, idempotency_key, and outcome_detail.
        mandatory_fields = [
            'timestamp', 'correlation_id', 'actor_id', 'chain_name',
            'step', 'outcome', 'latency_ms', 'idempotency_key', 'outcome_detail'
        ]
        for field in mandatory_fields:
            self.assertIn(field, log_data)

        # Check ISO 8601 formatting for timestamp in UTC (e.g. YYYY-MM-DDTHH:MM:SSZ)
        timestamp = log_data['timestamp']
        # Regex for YYYY-MM-DDTHH:MM:SSZ
        iso_regex = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
        self.assertTrue(re.match(iso_regex, timestamp), f"Timestamp '{timestamp}' is not in ISO 8601 UTC format")

        self.assertEqual(log_data['correlation_id'], "test_corr_123")
        self.assertEqual(log_data['actor_id'], "test_actor")
        self.assertEqual(log_data['chain_name'], "test_chain")
        self.assertEqual(log_data['step'], "test_step")
        self.assertEqual(log_data['outcome'], "success")
        self.assertEqual(log_data['latency_ms'], 42)
        self.assertEqual(log_data['idempotency_key'], "test_key_123")
        self.assertEqual(log_data['outcome_detail'], "test detail")

    def test_naming_conventions_in_dna_ui(self):
        """Verify that 'dna_sequence' is preferred over 'dna' in run_batch signature and other aspects."""
        sig = inspect.signature(dna_ui.run_batch)
        self.assertNotIn('dna', sig.parameters)

if __name__ == '__main__':
    unittest.main()
