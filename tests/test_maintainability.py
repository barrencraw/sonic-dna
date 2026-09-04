import os
import json
import shutil
import unittest
import tempfile
import io
from unittest.mock import patch

from utils.dna_ui import run_batch, DNAStatus, log_structured

class TestMaintainability(unittest.TestCase):
    def test_dnastatus_lowercase_values(self):
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_structured_logging_format(self):
        stdout_capture = io.StringIO()
        with patch('sys.stdout', stdout_capture):
            log_structured({
                'correlation_id': 'test-uuid-123',
                'actor_id': 'unit_test',
                'chain_name': 'dna_batch_parse',
                'step': 'parse_item',
                'outcome': 'success',
                'latency_ms': 12,
                'idempotency_key': 'VOL100',
                'outcome_detail': 'Test log'
            })

        log_str = stdout_capture.getvalue().strip()
        self.assertTrue(log_str.startswith("JSON_LOG:"))

        json_payload = json.loads(log_str.replace("JSON_LOG:", ""))
        self.assertEqual(json_payload['correlation_id'], 'test-uuid-123')
        self.assertEqual(json_payload['actor_id'], 'unit_test')
        self.assertEqual(json_payload['chain_name'], 'dna_batch_parse')
        self.assertEqual(json_payload['step'], 'parse_item')
        self.assertEqual(json_payload['outcome'], 'success')
        self.assertEqual(json_payload['latency_ms'], 12)
        self.assertEqual(json_payload['idempotency_key'], 'VOL100')
        self.assertEqual(json_payload['outcome_detail'], 'Test log')
        self.assertIn('timestamp', json_payload)

    def test_backwards_compatibility_keys(self):
        test_dir = tempfile.mkdtemp()
        data_dir = os.path.join(test_dir, 'data')
        raw_dir = os.path.join(data_dir, 'raw')
        output_dir = os.path.join(data_dir, 'output')
        rules_dir = os.path.join(test_dir, 'rules')

        os.makedirs(raw_dir)
        os.makedirs(output_dir)
        os.makedirs(rules_dir)

        with open(os.path.join(rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        input_file = os.path.join(raw_dir, 'toSequence.txt')
        with open(input_file, 'w') as f:
            f.write("VOL123\n")

        old_cwd = os.getcwd()
        os.chdir(test_dir)
        try:
            run_batch()

            json_out = os.path.join(output_dir, 'toSequence_parsed.json')
            with open(json_out, 'r') as f:
                data = json.load(f)

            self.assertEqual(len(data), 1)
            # Verify both 'dna' and 'dna_sequence' keys are present
            self.assertEqual(data[0]['dna'], 'VOL123')
            self.assertEqual(data[0]['dna_sequence'], 'VOL123')
        finally:
            os.chdir(old_cwd)
            shutil.rmtree(test_dir)

if __name__ == '__main__':
    unittest.main()
