import os
import json
import shutil
import tempfile
import unittest
from io import StringIO
from unittest.mock import patch

from utils.dna_ui import run_batch, DNAStatus

class TestMaintainability(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        # Volume rule
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "amp": {"min": 0, "max": 1000, "pad": 4, "description": "amp"},
                    "lr": {"min": 0, "max": 100, "pad": 3, "description": "lr"},
                    "sur": {"min": 0, "max": 10, "pad": 2, "description": "sur"},
                    "head": {"min": 0, "max": 60, "pad": 2, "description": "head"}
                }
            }, f)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.json_output = os.path.join(self.output_dir, 'toSequence_parsed.json')

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_dna_status_enum_lowercase(self):
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_output_fields_backward_compatibility(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch(correlation_id="test-compat")

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        self.assertEqual(len(data), 1)
        self.assertIn('dna', data[0])
        self.assertIn('dna_sequence', data[0])
        self.assertEqual(data[0]['dna'], dna)
        self.assertEqual(data[0]['dna_sequence'], dna)

    @patch('sys.stdout', new_callable=StringIO)
    def test_structured_telemetry_logs_format(self, mock_stdout):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch(correlation_id="test-telemetry-123", actor_id="test_runner")

        output = mock_stdout.getvalue()
        json_log_lines = [line for line in output.splitlines() if line.startswith("JSON_LOG:")]
        self.assertGreater(len(json_log_lines), 0)

        required_keys = {
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        }

        for line in json_log_lines:
            json_str = line.replace("JSON_LOG:", "").strip()
            payload = json.loads(json_str)
            for k in required_keys:
                self.assertIn(k, payload)
            self.assertEqual(payload["correlation_id"], "test-telemetry-123")
            self.assertEqual(payload["actor_id"], "test_runner")

if __name__ == '__main__':
    unittest.main()
