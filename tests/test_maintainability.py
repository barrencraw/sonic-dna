import os
import sys
import json
import io
import re
import shutil
import tempfile
import unittest
from unittest.mock import patch

from utils.dna_ui import (
    run_batch,
    log_structured,
    DNAStatus,
    DNAProcessingError,
    PersistenceError
)


class TestMaintainability(unittest.TestCase):
    def test_dna_status_enum_values(self):
        """Verify DNAStatus enum uses lowercase string values and converts cleanly to str."""
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")
        self.assertEqual(DNAStatus.REFUSED, "refused")
        self.assertEqual(str(DNAStatus.SUCCESS), "success")

    def test_structured_logging_schema(self):
        """Verify log_structured emits valid JSON prefixed with JSON_LOG: and expected schema."""
        captured_output = io.StringIO()
        with patch('sys.stdout', captured_output):
            log_structured(
                correlation_id="test-corr-schema",
                actor_id="test_actor",
                chain_name="dna_batch_parser",
                step="parse",
                outcome=DNAStatus.SUCCESS,
                latency_ms=12,
                idempotency_key="VOL08900750712",
                outcome_detail="Parsed OK"
            )

        output = captured_output.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "))

        json_part = output.replace("JSON_LOG: ", "", 1)
        data = json.loads(json_part)

        expected_schema_keys = {
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        }
        self.assertEqual(set(data.keys()), expected_schema_keys)

        # ISO 8601 UTC timestamp format check: YYYY-MM-DDTHH:MM:SSZ
        self.assertTrue(re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$', data["timestamp"]))
        self.assertEqual(data["outcome"], "success")
        self.assertEqual(data["correlation_id"], "test-corr-schema")

    def test_backward_compatibility_keys(self):
        """Verify parsed JSON outputs contain both legacy 'dna' and canonical 'dna_sequence' keys."""
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

            rule_file = os.path.join(rules_dir, 'rules_Volume.json')
            with open(rule_file, 'w', encoding='utf-8') as f:
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

            input_file = os.path.join(raw_dir, 'toSequence.txt')
            dna = "VOL08900750712"
            with open(input_file, 'w', encoding='utf-8') as f:
                f.write(dna + "\n")

            run_batch()

            json_out = os.path.join(output_dir, 'toSequence_parsed.json')
            with open(json_out, 'r', encoding='utf-8') as f:
                parsed = json.load(f)

            self.assertEqual(len(parsed), 1)
            self.assertIn('dna', parsed[0])
            self.assertIn('dna_sequence', parsed[0])
            self.assertEqual(parsed[0]['dna'], dna)
            self.assertEqual(parsed[0]['dna_sequence'], dna)

        finally:
            os.chdir(old_cwd)
            shutil.rmtree(test_dir)


if __name__ == '__main__':
    unittest.main()
