import unittest
import os
import json
import tempfile
import shutil
from unittest.mock import patch
import io

from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    RuleLoadError,
    InputReadError,
    PersistenceError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError,
    log_structured,
    run_batch
)

class TestMaintainability(unittest.TestCase):
    def test_dna_status_enum_values(self):
        """Verify explicit lowercase terminal outcome states."""
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")
        self.assertEqual(DNAStatus.REFUSED, "refused")

    def test_exception_taxonomy(self):
        """Verify typed error classification hierarchy."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_structured_log_format_and_fields(self):
        """Verify log_structured emits JSON_LOG: with required standard fields."""
        stdout_capture = io.StringIO()
        with patch('sys.stdout', stdout_capture):
            log_structured(
                correlation_id="test-cor-id",
                chain_name="dna_batch_parser",
                step="parse_sequence",
                outcome=DNAStatus.SUCCESS,
                latency_ms=12.345,
                actor_id="test_actor",
                idempotency_key="VOL100",
                outcome_detail="Parsed OK"
            )

        output = stdout_capture.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "))

        json_part = output[len("JSON_LOG: "):]
        log_data = json.loads(json_part)

        required_keys = {
            "timestamp",
            "correlation_id",
            "actor_id",
            "chain_name",
            "step",
            "outcome",
            "latency_ms",
            "idempotency_key",
            "outcome_detail"
        }
        for key in required_keys:
            self.assertIn(key, log_data, f"Missing required log field: {key}")

        self.assertEqual(log_data["correlation_id"], "test-cor-id")
        self.assertEqual(log_data["chain_name"], "dna_batch_parser")
        self.assertEqual(log_data["step"], "parse_sequence")
        self.assertEqual(log_data["outcome"], "success")
        self.assertEqual(log_data["actor_id"], "test_actor")
        self.assertEqual(log_data["idempotency_key"], "VOL100")

    def test_dto_naming_alignment(self):
        """Verify DTO output contains canonical 'dna_sequence' as well as legacy 'dna'."""
        test_dir = tempfile.mkdtemp()
        try:
            data_dir = os.path.join(test_dir, 'data')
            raw_dir = os.path.join(data_dir, 'raw')
            output_dir = os.path.join(data_dir, 'output')
            rules_dir = os.path.join(test_dir, 'rules')

            os.makedirs(raw_dir)
            os.makedirs(output_dir)
            os.makedirs(rules_dir)

            input_file = os.path.join(raw_dir, 'toSequence.txt')
            with open(input_file, 'w') as f:
                f.write("VOL08900750712\n")

            rule_file = os.path.join(rules_dir, 'rules_Volume.json')
            with open(rule_file, 'w') as f:
                json.dump({
                    "variable": "Volume",
                    "prefix": "VOL",
                    "subvars": {
                        "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                    }
                }, f)

            old_cwd = os.getcwd()
            os.chdir(test_dir)
            try:
                run_batch(correlation_id="test-dto", actor_id="maintainability_test")
            finally:
                os.chdir(old_cwd)

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
            shutil.rmtree(test_dir)

if __name__ == '__main__':
    unittest.main()
