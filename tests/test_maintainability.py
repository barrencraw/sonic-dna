import os
import io
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch

from utils.dna_ui import (
    run_batch,
    DNAStatus,
    DNAProcessingError,
    InputReadError,
    PersistenceError,
    RuleLoadError,
    LedgerSaveError,
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

        # Create valid volume rule
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w', encoding='utf-8') as f:
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

    def test_exception_taxonomy_hierarchy(self):
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))

    def test_structured_logging_keys(self):
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(input_file, 'w', encoding='utf-8') as f:
            f.write("VOL100\n")

        with patch('sys.stdout', new=io.StringIO()) as fake_out:
            run_batch(correlation_id="test-corr-123", actor_id="test_runner")
            output = fake_out.getvalue()

        log_lines = [line for line in output.splitlines() if line.startswith("JSON_LOG: ")]
        self.assertGreater(len(log_lines), 0, "Structured JSON logs should be emitted")

        required_keys = {
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        }

        for line in log_lines:
            json_str = line.replace("JSON_LOG: ", "").strip()
            payload = json.loads(json_str)
            self.assertTrue(required_keys.issubset(payload.keys()), f"Missing keys in payload: {payload}")
            self.assertEqual(payload["correlation_id"], "test-corr-123")
            self.assertEqual(payload["chain_name"], "dna_batch_parse")

    def test_naming_alignment_and_backwards_compatibility(self):
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(input_file, 'w', encoding='utf-8') as f:
            f.write("VOL500\n")

        run_batch()

        json_out_path = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        self.assertEqual(len(data), 1)
        entry = data[0]
        self.assertIn("dna_sequence", entry, "Canonical naming 'dna_sequence' must be present")
        self.assertIn("dna", entry, "Backwards compatible key 'dna' must be present")
        self.assertEqual(entry["dna_sequence"], "VOL500")
        self.assertEqual(entry["dna"], "VOL500")

    def test_explicit_terminal_states_in_ledger(self):
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(input_file, 'w', encoding='utf-8') as f:
            f.write("VOL123\nINVALID_PREFIX\n")

        run_batch()

        ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')
        with open(ledger_path, 'r', encoding='utf-8') as f:
            ledger = json.load(f)

        self.assertIn("VOL123", ledger)
        self.assertEqual(ledger["VOL123"]["terminal_outcome"], DNAStatus.SUCCESS.value)

        self.assertIn("INVALID_PREFIX", ledger)
        self.assertEqual(ledger["INVALID_PREFIX"]["terminal_outcome"], DNAStatus.ERROR.value)

if __name__ == '__main__':
    unittest.main()
