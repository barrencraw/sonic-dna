import os
import json
import shutil
import tempfile
import io
import sys
import unittest
from utils.dna_ui import run_batch, DNAStatus, LedgerLoadError, InputReadError, RuleLoadError

class TestMaintainability(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        # Mock a rule file
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_naming_alignment_and_structured_log_keys(self):
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(input_file, 'w') as f:
            f.write("VOL100\n")

        # Capture stdout to test structured logs
        stdout_capture = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = stdout_capture
            run_batch(correlation_id="test-corr-id-123")
        finally:
            sys.stdout = old_stdout

        output_logs = stdout_capture.getvalue().splitlines()
        json_logs = [line for line in output_logs if line.startswith("JSON_LOG:")]
        self.assertGreater(len(json_logs), 0)

        required_log_keys = {
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        }

        for log_line in json_logs:
            raw_json = log_line.replace("JSON_LOG:", "").strip()
            log_data = json.loads(raw_json)
            self.assertTrue(required_log_keys.issubset(log_data.keys()))
            self.assertEqual(log_data["correlation_id"], "test-corr-id-123")

        # Verify parsed JSON contains both canonical `dna_sequence` and legacy `dna` keys
        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)

        self.assertEqual(len(data), 1)
        self.assertIn('dna_sequence', data[0])
        self.assertIn('dna', data[0])
        self.assertEqual(data[0]['dna_sequence'], 'VOL100')
        self.assertEqual(data[0]['dna'], 'VOL100')

    def test_explicit_terminal_states(self):
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")

    def test_typed_ledger_load_error(self):
        ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')
        with open(ledger_path, 'w') as f:
            f.write("CORRUPTED_NOT_JSON")

        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(input_file, 'w') as f:
            f.write("VOL100\n")

        with self.assertRaises(LedgerLoadError):
            run_batch()

if __name__ == '__main__':
    unittest.main()
