import unittest
import inspect
import json
import re
from utils.dna_ui import (
    run_batch,
    log_structured,
    DNAStatus,
    DNAProcessingError,
    InputReadError,
    RuleLoadError,
    PersistenceError,
    LedgerSaveError,
    AtomicWriteError
)

class TestMaintainability(unittest.TestCase):
    def test_run_batch_signature(self):
        """Verify that run_batch has the canonical signature with correlation_id."""
        sig = inspect.signature(run_batch)
        self.assertIn('correlation_id', sig.parameters, "run_batch must accept a correlation_id parameter")

    def test_exception_taxonomy(self):
        """Verify the hierarchy of core DNA processing exceptions."""
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_status_enum_values(self):
        """Verify that DNAStatus uses lowercase string values for backward compatibility."""
        self.assertEqual(DNAStatus.SUCCESS.value, 'success')
        self.assertEqual(DNAStatus.ERROR.value, 'error')
        self.assertEqual(DNAStatus.SKIPPED.value, 'skipped')
        self.assertEqual(DNAStatus.REFUSED.value, 'refused')

    def test_log_structured_schema(self):
        """Verify that log_structured emits JSON with correct prefix and mandatory schema."""
        import sys
        from io import StringIO

        captured_output = StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = captured_output
            log_structured(
                step='test_step',
                outcome='success',
                latency_ms=123,
                correlation_id='corr-123',
                actor_id='user-456',
                chain_name='test_chain',
                idempotency_key='dna-789',
                outcome_detail='details-999'
            )
        finally:
            sys.stdout = old_stdout

        output_str = captured_output.getvalue().strip()
        self.assertTrue(output_str.startswith("JSON_LOG:"), "Log must start with prefix JSON_LOG:")

        json_part = output_str[len("JSON_LOG:"):]
        log_data = json.loads(json_part)

        mandatory_fields = [
            'timestamp', 'correlation_id', 'actor_id', 'chain_name',
            'step', 'outcome', 'latency_ms', 'idempotency_key', 'outcome_detail'
        ]
        for field in mandatory_fields:
            self.assertIn(field, log_data, f"Structured log must contain '{field}' field")

        # Verify timestamp format (ISO 8601 ending in Z, timezone-aware UTC)
        timestamp = log_data['timestamp']
        self.assertTrue(timestamp.endswith('Z'), "Timestamp must end with 'Z' indicating UTC timezone")
        # Match YYYY-MM-DDTHH:MM:SS.mmmmmmZ or YYYY-MM-DDTHH:MM:SSZ
        pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$'
        self.assertTrue(re.match(pattern, timestamp), f"Timestamp '{timestamp}' is not in valid ISO 8601 UTC format")

        # Verify exact logged fields
        self.assertEqual(log_data['correlation_id'], 'corr-123')
        self.assertEqual(log_data['actor_id'], 'user-456')
        self.assertEqual(log_data['chain_name'], 'test_chain')
        self.assertEqual(log_data['step'], 'test_step')
        self.assertEqual(log_data['outcome'], 'success')
        self.assertEqual(log_data['latency_ms'], 123)
        self.assertEqual(log_data['idempotency_key'], 'dna-789')
        self.assertEqual(log_data['outcome_detail'], 'details-999')
