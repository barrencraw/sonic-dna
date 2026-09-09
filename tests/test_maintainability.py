import os
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch, io
import sys

from utils.dna_calculator import DNACalculator
from utils.dna_ui import run_batch, DNAStatus, DNAProcessingError, RuleLoadError, PersistenceError, InputReadError

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

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
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
        shutil.rmtree(self.test_dir)

    def test_naming_alignment_dna_sequence(self):
        """Verify canonical name alignment: DNACalculator.parse and json output use dna_sequence."""
        calculator = DNACalculator(rules_folder=self.rules_dir)
        res = calculator.parse("VOL100")
        self.assertEqual(res['rule'], 'Volume')

        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("VOL100\n")

        run_batch(correlation_id="test_corr_id_001")

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertTrue(os.path.exists(json_out))
        with open(json_out, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertIn('dna_sequence', data[0])
            self.assertEqual(data[0]['dna_sequence'], 'VOL100')
            # Check backward compatibility key
            self.assertIn('dna', data[0])

    def test_structured_log_schema(self):
        """Verify that structured logs follow the required schema with all mandatory fields."""
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("VOL200\n")

        corr_id = "test_corr_id_999"

        with patch('sys.stdout', new=io.StringIO()) as fake_out:
            run_batch(correlation_id=corr_id)
            output = fake_out.getvalue()

        log_lines = [line for line in output.splitlines() if line.startswith("JSON_LOG:")]
        self.assertGreater(len(log_lines), 0, "Should emit JSON_LOG lines")

        required_keys = {
            "timestamp", "correlation_id", "chain_name", "step",
            "outcome", "latency_ms", "actor_id", "idempotency_key"
        }

        for line in log_lines:
            json_str = line.replace("JSON_LOG:", "")
            payload = json.loads(json_str)
            for k in required_keys:
                self.assertIn(k, payload, f"Missing key {k} in structured log")
            self.assertEqual(payload["correlation_id"], corr_id)
            self.assertEqual(payload["chain_name"], "dna_batch_parser")
            self.assertIn(payload["outcome"], [status.value for status in DNAStatus])

    def test_error_classification_and_terminal_states(self):
        """Verify typed error inheritance and terminal status enum values."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))

        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")

if __name__ == '__main__':
    unittest.main()
