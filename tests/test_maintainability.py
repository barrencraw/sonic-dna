import unittest
import json
import os
import shutil
import tempfile
from io import StringIO
from unittest.mock import patch
from utils.dna_ui import DNAStatus, log_structured, run_batch, load_ledger

class TestMaintainability(unittest.TestCase):
    def test_dna_status_lowercase_properties(self):
        self.assertEqual(DNAStatus.SUCCESS, 'success')
        self.assertEqual(DNAStatus.ERROR, 'error')
        self.assertEqual(DNAStatus.SKIPPED, 'skipped')
        self.assertEqual(DNAStatus.REFUSED, 'refused')

    def test_structured_log_format(self):
        output_buffer = StringIO()
        with patch('sys.stdout', output_buffer):
            log_structured(
                correlation_id="test_corr_id",
                actor_id="test_actor",
                chain_name="dna_batch_parser",
                step="process_sequence",
                outcome=DNAStatus.SUCCESS,
                latency_ms=12,
                idempotency_key="VOL00000000000",
                outcome_detail={"heat": 2.0}
            )

        log_output = output_buffer.getvalue().strip()
        self.assertTrue(log_output.startswith("JSON_LOG:"))

        json_part = log_output[len("JSON_LOG:"):]
        parsed = json.loads(json_part)

        required_keys = [
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        ]
        for key in required_keys:
            self.assertIn(key, parsed)

        self.assertEqual(parsed["correlation_id"], "test_corr_id")
        self.assertEqual(parsed["actor_id"], "test_actor")
        self.assertEqual(parsed["outcome"], "success")

    def test_backwards_compatibility_keys(self):
        test_dir = tempfile.mkdtemp()
        old_cwd = os.getcwd()
        try:
            os.chdir(test_dir)
            raw_dir = os.path.join(test_dir, 'data', 'raw')
            output_dir = os.path.join(test_dir, 'data', 'output')
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

            with open(os.path.join(raw_dir, 'toSequence.txt'), 'w') as f:
                f.write("VOL100\n")

            run_batch()

            json_out = os.path.join(output_dir, 'toSequence_parsed.json')
            with open(json_out, 'r') as f:
                data = json.load(f)

            self.assertEqual(len(data), 1)
            # Verify both canonical 'dna_sequence' and legacy 'dna' keys exist
            self.assertIn('dna', data[0])
            self.assertIn('dna_sequence', data[0])
            self.assertEqual(data[0]['dna'], 'VOL100')
            self.assertEqual(data[0]['dna_sequence'], 'VOL100')

        finally:
            os.chdir(old_cwd)
            shutil.rmtree(test_dir)

if __name__ == '__main__':
    unittest.main()
