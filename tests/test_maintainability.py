import os
import json
import io
import contextlib
import tempfile
import unittest
from utils.dna_ui import (
    run_batch,
    DNAStatus,
    DNAProcessingError,
    InputReadError,
    LedgerLoadError,
    AtomicWriteError
)

class TestMaintainabilityAndSignal(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        # Mock a Volume rule file
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w', encoding='utf-8') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)

    def test_structured_log_schema_and_canonical_naming(self):
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(input_file, 'w', encoding='utf-8') as f:
            f.write("VOL100\n")

        stdout_buffer = io.StringIO()
        with contextlib.redirect_stdout(stdout_buffer):
            run_batch(correlation_id="test-corr-1234")

        output_str = stdout_buffer.getvalue()
        lines = [line for line in output_str.split('\n') if line.startswith("JSON_LOG:")]
        self.assertTrue(len(lines) > 0, "Expected JSON_LOG output entries")

        mandatory_keys = {
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        }

        for line in lines:
            json_payload = line.replace("JSON_LOG: ", "").strip()
            log_dict = json.loads(json_payload)
            self.assertTrue(mandatory_keys.issubset(set(log_dict.keys())), f"Missing keys in log: {log_dict}")
            self.assertEqual(log_dict["correlation_id"], "test-corr-1234")

        # Verify canonical name in JSON output
        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r', encoding='utf-8') as f:
            parsed = json.load(f)
            self.assertEqual(len(parsed), 1)
            self.assertIn("dna_sequence", parsed[0])
            self.assertIn("dna", parsed[0]) # Backward compatibility
            self.assertEqual(parsed[0]["dna_sequence"], "VOL100")

    def test_typed_exception_classification(self):
        # Test InputReadError when raw input file is missing
        with self.assertRaises(InputReadError):
            run_batch()

        # Test LedgerLoadError on corrupted ledger
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(input_file, 'w', encoding='utf-8') as f:
            f.write("VOL100\n")

        ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')
        with open(ledger_path, 'w', encoding='utf-8') as f:
            f.write("{ INVALID JSON }")

        with self.assertRaises(LedgerLoadError):
            run_batch()

    def test_status_enum_values(self):
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")

if __name__ == '__main__':
    unittest.main()
