import unittest
import json
import os
import shutil
import tempfile
from io import StringIO
from unittest.mock import patch
from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    InputReadError,
    RuleLoadError,
    PersistenceError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError,
    ThermalOverloadError,
    log_structured,
    run_batch,
)


class TestMaintainabilityAndSignal(unittest.TestCase):
    def test_dna_status_enum_values(self):
        """Verify DNAStatus enum uses lowercase string values for compatibility."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_exception_taxonomy_hierarchy(self):
        """Verify exception hierarchy subclass relationships."""
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))
        self.assertTrue(issubclass(ThermalOverloadError, DNAProcessingError))

    def test_structured_log_schema(self):
        """Verify log_structured outputs JSON with JSON_LOG: prefix and mandatory keys."""
        buffer = StringIO()
        with patch('sys.stdout', buffer):
            log_structured(
                event="test_event",
                correlation_id="trace-123",
                actor_id="test_actor",
                chain_name="dna_batch_parser",
                step="test_step",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=12.34,
                idempotency_key="VOL100",
                outcome_detail="test_detail"
            )

        output = buffer.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "))

        json_str = output[len("JSON_LOG: "):]
        payload = json.loads(json_str)

        required_keys = [
            "timestamp",
            "correlation_id",
            "actor_id",
            "chain_name",
            "step",
            "outcome",
            "latency_ms",
            "idempotency_key",
            "outcome_detail"
        ]

        for key in required_keys:
            self.assertIn(key, payload, f"Missing required log field: {key}")

        self.assertEqual(payload["correlation_id"], "trace-123")
        self.assertEqual(payload["actor_id"], "test_actor")
        self.assertEqual(payload["chain_name"], "dna_batch_parser")
        self.assertEqual(payload["step"], "test_step")
        self.assertEqual(payload["outcome"], "success")

    def test_output_schema_contains_canonical_and_legacy_keys(self):
        """Verify parsed JSON and CSV outputs contain both 'dna_sequence' and 'dna' keys."""
        test_dir = tempfile.mkdtemp()
        old_cwd = os.getcwd()
        try:
            os.chdir(test_dir)
            raw_dir = os.path.join(test_dir, 'data', 'raw')
            output_dir = os.path.join(test_dir, 'data', 'output')
            rules_dir = os.path.join(test_dir, 'rules')
            os.makedirs(raw_dir, exist_ok=True)
            os.makedirs(output_dir, exist_ok=True)
            os.makedirs(rules_dir, exist_ok=True)

            # Copy rules from project root
            for fname in os.listdir(os.path.join(old_cwd, 'rules')):
                if fname.endswith('.json'):
                    shutil.copy(
                        os.path.join(old_cwd, 'rules', fname),
                        os.path.join(rules_dir, fname)
                    )

            # Write input sequence for Volume (VOL prefix)
            input_file = os.path.join(raw_dir, 'toSequence.txt')
            with open(input_file, 'w') as f:
                f.write("VOL08900750712\n")

            run_batch()

            json_out = os.path.join(output_dir, 'toSequence_parsed.json')
            self.assertTrue(os.path.exists(json_out))

            with open(json_out, 'r') as f:
                data = json.load(f)

            self.assertEqual(len(data), 1)
            entry = data[0]
            self.assertIn('dna_sequence', entry)
            self.assertIn('dna', entry)
            self.assertEqual(entry['dna_sequence'], "VOL08900750712")
            self.assertEqual(entry['dna'], "VOL08900750712")

        finally:
            os.chdir(old_cwd)
            shutil.rmtree(test_dir)


if __name__ == '__main__':
    unittest.main()
