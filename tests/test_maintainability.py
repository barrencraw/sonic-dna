import inspect
import json
import re
import unittest
from unittest.mock import patch
from utils.dna_ui import run_batch, log_structured, DNAStatus, BatchResult

class TestMaintainability(unittest.TestCase):
    def test_run_batch_signature(self):
        """Verify that run_batch has correlation_id parameter in its signature."""
        sig = inspect.signature(run_batch)
        self.assertIn('correlation_id', sig.parameters, "run_batch must accept correlation_id as a parameter.")
        # Also verify it has default value of None
        param = sig.parameters['correlation_id']
        self.assertEqual(param.default, None, "correlation_id must default to None.")

    def test_dna_status_enum(self):
        """Verify that DNAStatus enum utilizes lowercase values to preserve backward compatibility."""
        self.assertEqual(DNAStatus.SUCCESS, 'success')
        self.assertEqual(DNAStatus.ERROR, 'error')
        self.assertEqual(DNAStatus.SKIPPED, 'skipped')
        self.assertEqual(DNAStatus.REFUSED, 'refused')

    def test_batch_result_properties(self):
        """Verify BatchResult has the required properties: status, processed_count, and total_ledger_items."""
        result = BatchResult(status='SUCCESS', processed_count=5, total_ledger_items=10)
        self.assertTrue(hasattr(result, 'status'))
        self.assertTrue(hasattr(result, 'processed_count'))
        self.assertTrue(hasattr(result, 'total_ledger_items'))
        self.assertEqual(result.status, 'SUCCESS')
        self.assertEqual(result.processed_count, 5)
        self.assertEqual(result.total_ledger_items, 10)

    def test_structured_logging(self):
        """Verify that log_structured prints JSON logs in the correct format with mandatory fields."""
        with patch('builtins.print') as mock_print:
            log_structured(
                correlation_id="test-corr-id",
                actor_id="test-actor-id",
                chain_name="test-chain",
                step="test-step",
                outcome="test-outcome",
                latency_ms=123.45,
                idempotency_key="test-key",
                outcome_detail="test-detail"
            )

            # Assert print was called once
            mock_print.assert_called_once()
            print_arg = mock_print.call_args[0][0]

            # Assert prefix
            self.assertTrue(print_arg.startswith("JSON_LOG: "), f"Log must start with 'JSON_LOG: ', got: {print_arg}")

            # Parse JSON
            json_str = print_arg[len("JSON_LOG: "):]
            log_data = json.loads(json_str)

            # Assert mandatory keys presence
            mandatory_keys = [
                'timestamp', 'correlation_id', 'actor_id', 'chain_name',
                'step', 'outcome', 'latency_ms', 'idempotency_key', 'outcome_detail'
            ]
            for key in mandatory_keys:
                self.assertIn(key, log_data, f"Mandatory log key '{key}' is missing from structured log.")

            # Assert value types and values
            self.assertEqual(log_data['correlation_id'], "test-corr-id")
            self.assertEqual(log_data['actor_id'], "test-actor-id")
            self.assertEqual(log_data['chain_name'], "test-chain")
            self.assertEqual(log_data['step'], "test-step")
            self.assertEqual(log_data['outcome'], "test-outcome")
            self.assertEqual(log_data['latency_ms'], 123)  # Cast to int
            self.assertEqual(log_data['idempotency_key'], "test-key")
            self.assertEqual(log_data['outcome_detail'], "test-detail")

            # Assert ISO 8601 formatting (with Z for UTC)
            timestamp = log_data['timestamp']
            pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$'
            self.assertTrue(re.match(pattern, timestamp), f"Timestamp '{timestamp}' does not match ISO 8601 UTC format with Z.")

if __name__ == '__main__':
    unittest.main()
