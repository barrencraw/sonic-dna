import unittest
import inspect
import io
import json
import datetime
from contextlib import redirect_stdout
from utils import dna_ui


class TestMaintainability(unittest.TestCase):
    def test_naming_and_signatures(self):
        """
        Verify canonical naming conventions and parameter signatures.
        """
        # Ensure run_batch has correlation_id as a parameter
        sig = inspect.signature(dna_ui.run_batch)
        self.assertIn('correlation_id', sig.parameters, "run_batch must accept correlation_id")

        # Ensure alias main points to run_batch
        self.assertEqual(dna_ui.main, dna_ui.run_batch, "main alias must point to run_batch")

        # Ensure we enforce canonical names 'dna_sequence' / 'dna_sequence_list' in read_input_file
        read_input_sig = inspect.signature(dna_ui.read_input_file)
        # The argument name or return can be inspected, but checking signature of other helpers helps
        # Also let's inspect the code of read_input_file to verify it uses dna_sequence_list
        source = inspect.getsource(dna_ui.read_input_file)
        self.assertIn("dna_sequence_list", source, "read_input_file should use canonical collection name 'dna_sequence_list'")

    def test_observability_structured_logs(self):
        """
        Verify log_structured prints standardized logs with all mandatory fields and correct ISO 8601 format.
        """
        f = io.StringIO()
        with redirect_stdout(f):
            dna_ui.log_structured(
                correlation_id="test-corr-id-123",
                step="test_step",
                outcome="success",
                latency_ms=12.5,
                actor_id="test_actor",
                idempotency_key="test_key",
                outcome_detail="test detail"
            )

        output = f.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG:"), "Log must be prefixed with 'JSON_LOG:'")

        # Extract the JSON part
        json_str = output[len("JSON_LOG:"):]
        log_data = json.loads(json_str)

        # Assert mandatory fields are present
        mandatory_fields = [
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        ]
        for field in mandatory_fields:
            self.assertIn(field, log_data, f"Mandatory log field '{field}' is missing")

        # Validate values
        self.assertEqual(log_data["correlation_id"], "test-corr-id-123")
        self.assertEqual(log_data["step"], "test_step")
        self.assertEqual(log_data["outcome"], "success")
        self.assertEqual(log_data["latency_ms"], 12.5)
        self.assertEqual(log_data["actor_id"], "test_actor")
        self.assertEqual(log_data["idempotency_key"], "test_key")
        self.assertEqual(log_data["outcome_detail"], "test detail")
        self.assertEqual(log_data["chain_name"], "dna_batch_parsing_chain")

        # Validate timestamp format (%Y-%m-%dT%H:%M:%SZ)
        ts = log_data["timestamp"]
        self.assertTrue(ts.endswith("Z"), "Timestamp must end with 'Z' to indicate UTC")
        try:
            parsed_dt = datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError as e:
            self.fail(f"Timestamp '{ts}' does not follow precise ISO 8601 UTC format %Y-%m-%dT%H:%M:%SZ: {e}")

    def test_custom_exception_hierarchy(self):
        """
        Verify the typed error classification hierarchy.
        """
        self.assertTrue(issubclass(dna_ui.RuleLoadError, dna_ui.DNAProcessingError))
        self.assertTrue(issubclass(dna_ui.PersistenceError, dna_ui.DNAProcessingError))
        self.assertTrue(issubclass(dna_ui.LedgerError, dna_ui.DNAProcessingError))
        self.assertTrue(issubclass(dna_ui.LedgerLoadError, dna_ui.LedgerError))
        self.assertTrue(issubclass(dna_ui.LedgerSaveError, dna_ui.LedgerError))
        self.assertTrue(issubclass(dna_ui.LedgerSaveError, dna_ui.PersistenceError))


if __name__ == "__main__":
    unittest.main()
