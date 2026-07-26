import os
import ast
import json
import unittest
from unittest.mock import patch, MagicMock
from utils.dna_ui import DNAStatus, log_structured, run_batch

class TestMaintainability(unittest.TestCase):

    def test_canonical_naming_convention(self):
        """
        Verify that utils/dna_ui.py adheres to naming alignment.
        Ensures 'dna_sequence_list' is used as a variable name and 'dna_list' is not used.
        """
        ui_filepath = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'utils', 'dna_ui.py')
        with open(ui_filepath, 'r', encoding='utf-8') as f:
            source = f.read()

        tree = ast.parse(source)

        # Traverse the AST to check defined/assigned variables or parameters
        var_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                var_names.add(node.id)
            elif isinstance(node, ast.arg):
                var_names.add(node.arg)

        # Assert that 'dna_sequence_list' is present in the source
        self.assertIn('dna_sequence_list', var_names, "Should use the canonical collection name 'dna_sequence_list'")
        # Assert that 'dna_list' is NOT present in the source
        self.assertNotIn('dna_list', var_names, "Should NOT use the legacy collection name 'dna_list'")

    def test_dna_status_enum_values(self):
        """
        Verify that DNAStatus contains lowercase terminal states for backward compatibility.
        """
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")
        self.assertEqual(DNAStatus.REFUSED, "refused")

    def test_log_structured_format_and_keys(self):
        """
        Verify that log_structured emits logs in exact JSON format with the JSON_LOG: prefix
        and contains all the mandatory structured log keys, including precise ISO 8601 UTC timestamp.
        """
        import sys
        from io import StringIO

        captured_stdout = StringIO()
        with patch('sys.stdout', new=captured_stdout):
            log_structured(
                correlation_id="test-corr-id",
                actor_id="test-actor",
                chain_name="test-chain",
                step="test-step",
                outcome=DNAStatus.SUCCESS,
                latency_ms=42,
                idempotency_key="test-key",
                outcome_detail="test-detail"
            )

        output = captured_stdout.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "))

        log_json_str = output[len("JSON_LOG: "):]
        log_data = json.loads(log_json_str)

        # Check mandatory fields
        mandatory_keys = {
            'timestamp', 'correlation_id', 'actor_id', 'chain_name', 'step',
            'outcome', 'latency_ms', 'idempotency_key', 'outcome_detail'
        }
        for key in mandatory_keys:
            self.assertIn(key, log_data, f"Mandatory log key '{key}' missing")

        # Check field values
        self.assertEqual(log_data['correlation_id'], "test-corr-id")
        self.assertEqual(log_data['actor_id'], "test-actor")
        self.assertEqual(log_data['chain_name'], "test-chain")
        self.assertEqual(log_data['step'], "test-step")
        self.assertEqual(log_data['outcome'], "success")
        self.assertEqual(log_data['latency_ms'], 42)
        self.assertEqual(log_data['idempotency_key'], "test-key")
        self.assertEqual(log_data['outcome_detail'], "test-detail")

        # Verify UTC ISO 8601 format: YYYY-MM-DDTHH:MM:SSZ
        timestamp_str = log_data['timestamp']
        self.assertTrue(timestamp_str.endswith('Z'), "Timestamp must be UTC and end with 'Z'")
        # Verify it can be parsed using the expected format %Y-%m-%dT%H:%M:%SZ
        import datetime
        try:
            datetime.datetime.strptime(timestamp_str, '%Y-%m-%dT%H:%M:%SZ')
        except ValueError:
            self.fail(f"Timestamp '{timestamp_str}' does not match ISO 8601 UTC format %Y-%m-%dT%H:%M:%SZ")

if __name__ == '__main__':
    unittest.main()
