import os
import io
import json
import csv
import unittest
import datetime
import inspect
from unittest.mock import patch
from utils.dna_ui import run_batch, log_structured, DNAStatus

class TestMaintainability(unittest.TestCase):
    def test_dnastatus_enum_properties_lowercase(self):
        """Verify that DNAStatus string enum values are strictly lowercase to preserve backward compatibility."""
        for status in DNAStatus:
            self.assertEqual(status.value, status.value.lower())
            self.assertIn(status.value, ['success', 'error', 'skipped', 'refused'])

    def test_log_structured_schema_and_iso8601(self):
        """Verify that log_structured emits JSON with correct prefix, mandatory fields, and ISO 8601 timestamp."""
        with patch('sys.stdout', new=io.StringIO()) as mock_stdout:
            log_structured(
                step="test_step",
                outcome="success",
                latency_ms=123,
                idempotency_key="TEST_DNA_KEY",
                outcome_detail="Detailed test outcome",
                correlation_id="TEST_CORR_ID"
            )
            output = mock_stdout.getvalue().strip()

            # Assert prefix
            self.assertTrue(output.startswith("JSON_LOG: "))
            json_str = output[len("JSON_LOG: "):]

            # Parse and validate JSON
            log_data = json.loads(json_str)
            mandatory_fields = [
                'timestamp', 'correlation_id', 'actor_id', 'chain_name',
                'step', 'outcome', 'latency_ms', 'idempotency_key', 'outcome_detail'
            ]
            for field in mandatory_fields:
                self.assertIn(field, log_data)

            # Verify values
            self.assertEqual(log_data['correlation_id'], "TEST_CORR_ID")
            self.assertEqual(log_data['actor_id'], "sonicdna_system")
            self.assertEqual(log_data['chain_name'], "dna_batch_parsing_chain")
            self.assertEqual(log_data['step'], "test_step")
            self.assertEqual(log_data['outcome'], "success")
            self.assertEqual(log_data['latency_ms'], 123)
            self.assertEqual(log_data['idempotency_key'], "TEST_DNA_KEY")
            self.assertEqual(log_data['outcome_detail'], "Detailed test outcome")

            # Verify ISO 8601 timestamp (e.g. 2026-03-02T15:20:11.123456Z or 2026-03-02T15:20:11.123456)
            ts = log_data['timestamp']
            # Should be able to parse it with datetime.fromisoformat
            try:
                # Handle 'Z' representation if present
                if ts.endswith('Z'):
                    parsed_ts = datetime.datetime.fromisoformat(ts[:-1] + '+00:00')
                else:
                    parsed_ts = datetime.datetime.fromisoformat(ts)
            except ValueError as e:
                self.fail(f"Timestamp '{ts}' is not in a valid ISO 8601 format: {e}")

    def test_run_batch_signature_parameters(self):
        """Verify that the entry point accepts 'correlation_id' keyword parameter."""
        sig = inspect.signature(run_batch)
        self.assertIn('correlation_id', sig.parameters)
        self.assertEqual(sig.parameters['correlation_id'].default, None)

    def test_backward_compatibility_keys_in_outputs(self):
        """Verify that the parser writes both 'dna' and 'dna_sequence' keys to maintain compatibility."""
        # Create a temporary project structure for running a simple run
        import tempfile
        import shutil

        test_dir = tempfile.mkdtemp()
        old_cwd = os.getcwd()
        try:
            os.chdir(test_dir)

            # Create rules, data folders
            rules_dir = os.path.join(test_dir, 'rules')
            os.makedirs(rules_dir)
            raw_dir = os.path.join(test_dir, 'data', 'raw')
            os.makedirs(raw_dir)
            output_dir = os.path.join(test_dir, 'data', 'output')
            os.makedirs(output_dir)

            # Mock rule Volume
            with open(os.path.join(rules_dir, 'rules_Volume.json'), 'w') as f:
                json.dump({
                    "variable": "Volume",
                    "prefix": "VOL",
                    "subvars": {
                        "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                    }
                }, f)

            # Input sequence
            with open(os.path.join(raw_dir, 'toSequence.txt'), 'w') as f:
                f.write("VOL123\n")

            # Run batch
            run_batch()

            # Verify outputs contain both keys
            json_out = os.path.join(output_dir, 'toSequence_parsed.json')
            self.assertTrue(os.path.exists(json_out))
            with open(json_out, 'r') as f:
                data = json.load(f)
                self.assertEqual(len(data), 1)
                self.assertEqual(data[0]['dna'], 'VOL123')
                self.assertEqual(data[0]['dna_sequence'], 'VOL123')

            csv_out = os.path.join(output_dir, 'toSequence_parsed.csv')
            self.assertTrue(os.path.exists(csv_out))
            with open(csv_out, 'r') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['dna'], 'VOL123')
                self.assertEqual(rows[0]['dna_sequence'], 'VOL123')

        finally:
            os.chdir(old_cwd)
            shutil.rmtree(test_dir)

if __name__ == '__main__':
    unittest.main()
