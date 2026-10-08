import os
import json
import io
import sys
import unittest
import tempfile
import shutil
from unittest.mock import patch

from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    InputReadError,
    RuleLoadError,
    PersistenceError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError,
    log_structured,
    load_ledger,
    main as run_batch
)

class TestMaintainabilityAndSignal(unittest.TestCase):
    def test_dna_status_enum_values(self):
        """Verify DNAStatus string enum values preserve backward compatibility."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_exception_taxonomy(self):
        """Verify typed error inheritance hierarchy."""
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_ledger_load_error_on_corrupted_json(self):
        """Verify load_ledger raises typed LedgerLoadError on corrupted json."""
        tmp_file = tempfile.NamedTemporaryFile('w', delete=False)
        try:
            tmp_file.write("INVALID JSON {{{")
            tmp_file.close()

            with self.assertRaises(LedgerLoadError):
                load_ledger(tmp_file.name)
        finally:
            if os.path.exists(tmp_file.name):
                os.remove(tmp_file.name)

    def test_structured_logging_schema(self):
        """Verify log_structured emits JSON_LOG with all required standard fields."""
        captured_output = io.StringIO()
        with patch('sys.stdout', new=captured_output):
            log_structured(
                correlation_id="test-corr-123",
                actor_id="test_actor",
                chain_name="test_chain",
                step="test_step",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=12.345,
                idempotency_key="VOL100",
                outcome_detail="All clear"
            )

        out = captured_output.getvalue().strip()
        self.assertTrue(out.startswith("JSON_LOG:"))

        json_str = out[len("JSON_LOG:"):].strip()
        data = json.loads(json_str)

        required_fields = [
            "timestamp",
            "correlation_id",
            "actor_id",
            "chain_name",
            "step",
            "outcome",
            "latency_ms",
            "idempotency_key",
            "outcome_detail"
        ]
        for field in required_fields:
            self.assertIn(field, data, f"Missing required telemetry key: {field}")

        self.assertEqual(data["correlation_id"], "test-corr-123")
        self.assertEqual(data["actor_id"], "test_actor")
        self.assertEqual(data["chain_name"], "test_chain")
        self.assertEqual(data["step"], "test_step")
        self.assertEqual(data["outcome"], "success")
        self.assertEqual(data["latency_ms"], 12.345)
        self.assertEqual(data["idempotency_key"], "VOL100")
        self.assertEqual(data["outcome_detail"], "All clear")

    def test_naming_alignment_and_dual_keys(self):
        """Verify batch parsing produces both canonical dna_sequence and legacy dna keys."""
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

            # Copy volume rule file into sandbox
            src_rule = os.path.join(os.getcwd(), 'rules', 'rules_Volume.json')
            if os.path.exists(src_rule):
                shutil.copy(src_rule, rules_dir)
            else:
                rule_file = os.path.join(rules_dir, 'rules_Volume.json')
                with open(rule_file, 'w') as f:
                    json.dump({
                        "variable": "Volume",
                        "prefix": "VOL",
                        "subvars": {
                            "v1": {"description": "v1", "min": 0, "max": 999, "pad": 3},
                            "v2": {"description": "v2", "min": 0, "max": 999, "pad": 3},
                            "v3": {"description": "v3", "min": 0, "max": 999, "pad": 3},
                            "v4": {"description": "v4", "min": 0, "max": 999, "pad": 3}
                        }
                    }, f)

            old_cwd = os.getcwd()
            os.chdir(test_dir)
            try:
                run_batch(correlation_id="test-batch-run", actor_id="maintainability_test")

                json_out = os.path.join(output_dir, 'toSequence_parsed.json')
                self.assertTrue(os.path.exists(json_out))

                with open(json_out, 'r') as f:
                    data = json.load(f)

                self.assertEqual(len(data), 1)
                self.assertIn('dna_sequence', data[0], "Canonical key 'dna_sequence' missing in DTO")
                self.assertIn('dna', data[0], "Legacy key 'dna' missing in DTO")
                self.assertEqual(data[0]['dna_sequence'], "VOL08900750712")
                self.assertEqual(data[0]['dna'], "VOL08900750712")
            finally:
                os.chdir(old_cwd)
        finally:
            shutil.rmtree(test_dir)

if __name__ == '__main__':
    unittest.main()
