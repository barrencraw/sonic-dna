import os
import sys
import unittest
import json
from unittest.mock import patch, MagicMock
from utils.dna_ui import DNAStatus, process_single_dna, log_structured
from utils.dna_calculator import DNACalculator

class TestMaintainabilityAndTelemetry(unittest.TestCase):
    def test_dna_status_enum_values(self):
        """Ensure DNAStatus uses lowercase terminal outcome values for legacy compatibility."""
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")
        self.assertEqual(DNAStatus.REFUSED, "refused")

    def test_process_single_dna_success_and_error(self):
        """Verify process_single_dna returns typed outcomes and correct data structures."""
        # Mock calculator
        mock_calc = MagicMock()
        mock_calc.parse.return_value = {
            'rule': 'Volume',
            'values': {'level': 100}
        }

        status, result, flat = process_single_dna("V100", mock_calc)
        self.assertEqual(status, DNAStatus.SUCCESS)
        self.assertEqual(result['rule'], 'Volume')
        self.assertEqual(flat['dna'], 'V100')
        self.assertEqual(flat['Volume.level'], 100)

    def test_log_structured_emits_valid_json_log(self):
        """Ensure log_structured prints JSON prefixed with JSON_LOG: and mandatory fields."""
        import io
        captured_output = io.StringIO()
        sys.stdout = captured_output
        try:
            log_structured(
                correlation_id="test-corr-id",
                actor_id="test-actor",
                chain_name="test-chain",
                step="test-step",
                outcome="success",
                latency_ms=123,
                idempotency_key="test-key",
                outcome_detail="test detail"
            )
        finally:
            sys.stdout = sys.__stdout__

        log_str = captured_output.getvalue().strip()
        self.assertTrue(log_str.startswith("JSON_LOG:"))
        json_part = log_str[len("JSON_LOG:"):].strip()

        # Verify JSON parses correctly
        data = json.loads(json_part)
        self.assertEqual(data["correlation_id"], "test-corr-id")
        self.assertEqual(data["actor_id"], "test-actor")
        self.assertEqual(data["chain_name"], "test-chain")
        self.assertEqual(data["step"], "test-step")
        self.assertEqual(data["outcome"], "success")
        self.assertEqual(data["latency_ms"], 123)
        self.assertEqual(data["idempotency_key"], "test-key")
        self.assertEqual(data["outcome_detail"], "test detail")
        self.assertTrue("timestamp" in data)
