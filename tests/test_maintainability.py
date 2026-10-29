import os
import io
import sys
import json
import shutil
import tempfile
import unittest
from utils.dna_ui import (
    log_structured, DNAStatus, DNAProcessingError, RuleLoadError,
    InputReadError, PersistenceError, LedgerLoadError, LedgerSaveError,
    AtomicWriteError, run_batch
)

class TestMaintainability(unittest.TestCase):
    def test_log_structured_format(self):
        captured_output = io.StringIO()
        original_stdout = sys.stdout
        try:
            sys.stdout = captured_output
            log_structured(
                chain_name="test_chain",
                step="test_step",
                outcome="success",
                latency_ms=12.34,
                correlation_id="corr-123",
                actor_id="test_actor",
                idempotency_key="key-456",
                outcome_detail="test detail"
            )
        finally:
            sys.stdout = original_stdout

        output = captured_output.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG:"))

        json_str = output[len("JSON_LOG:"):].strip()
        log_entry = json.loads(json_str)

        required_keys = [
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        ]
        for key in required_keys:
            self.assertIn(key, log_entry)

        self.assertEqual(log_entry["correlation_id"], "corr-123")
        self.assertEqual(log_entry["actor_id"], "test_actor")
        self.assertEqual(log_entry["chain_name"], "test_chain")
        self.assertEqual(log_entry["step"], "test_step")
        self.assertEqual(log_entry["outcome"], "success")
        self.assertEqual(log_entry["idempotency_key"], "key-456")
        self.assertEqual(log_entry["outcome_detail"], "test detail")

    def test_exception_taxonomy_inheritance(self):
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_dnastatus_enum_properties(self):
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_backward_compatibility_fields(self):
        test_dir = tempfile.mkdtemp()
        data_dir = os.path.join(test_dir, 'data')
        raw_dir = os.path.join(data_dir, 'raw')
        output_dir = os.path.join(data_dir, 'output')
        rules_dir = os.path.join(test_dir, 'rules')

        os.makedirs(raw_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(rules_dir, exist_ok=True)

        input_file = os.path.join(raw_dir, 'toSequence.txt')
        json_output = os.path.join(output_dir, 'toSequence_parsed.json')

        rule_file = os.path.join(rules_dir, 'rules_Volume.json')
        with open(rule_file, 'w', encoding='utf-8') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        dna = "VOL123"
        with open(input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        old_cwd = os.getcwd()
        os.chdir(test_dir)
        try:
            run_batch(correlation_id="test-compat")
            with open(json_output, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertIn("dna", data[0])
            self.assertIn("dna_sequence", data[0])
            self.assertEqual(data[0]["dna"], dna)
            self.assertEqual(data[0]["dna_sequence"], dna)
        finally:
            os.chdir(old_cwd)
            shutil.rmtree(test_dir)

if __name__ == '__main__':
    unittest.main()
