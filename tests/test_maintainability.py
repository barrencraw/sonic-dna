import unittest
import inspect
import json
import io
import contextlib
import os
import shutil
import tempfile
from utils.dna_calculator import Rule, DNACalculator
from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    RuleLoadError,
    InputReadError,
    PersistenceError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError,
    ThermalOverloadError,
    log_structured,
    run_batch
)

class TestMaintainability(unittest.TestCase):
    def test_naming_alignment_parameters_and_keys(self):
        """Verify method signatures use canonical parameter dna_sequence."""
        rule_sig = inspect.signature(Rule.parse)
        self.assertIn('dna_sequence', rule_sig.parameters)

        calc_sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', calc_sig.parameters)

    def test_exception_taxonomy_hierarchy(self):
        """Verify exception hierarchy and typed classifications."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))
        self.assertTrue(issubclass(ThermalOverloadError, DNAProcessingError))

    def test_dna_status_enum_lowercase_values(self):
        """Verify DNAStatus enum string representation and values are lowercase."""
        self.assertEqual(DNAStatus.SUCCESS.value, 'success')
        self.assertEqual(DNAStatus.ERROR.value, 'error')
        self.assertEqual(DNAStatus.SKIPPED.value, 'skipped')
        self.assertEqual(DNAStatus.REFUSED.value, 'refused')
        self.assertEqual(str(DNAStatus.SUCCESS), 'success')

    def test_structured_logging_schema(self):
        """Verify log_structured emits JSON with mandatory telemetry keys."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            log_structured(
                chain_name="test_chain",
                step="test_step",
                outcome=DNAStatus.SUCCESS,
                correlation_id="test-corr-id",
                actor_id="test-actor",
                latency_ms=42,
                idempotency_key="VOL100",
                outcome_detail="test detail"
            )

        output = buf.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "))

        json_str = output.replace("JSON_LOG: ", "", 1)
        data = json.loads(json_str)

        required_keys = [
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

        for k in required_keys:
            self.assertIn(k, data, f"Missing required log key: {k}")

        self.assertEqual(data["chain_name"], "test_chain")
        self.assertEqual(data["step"], "test_step")
        self.assertEqual(data["outcome"], "success")
        self.assertEqual(data["correlation_id"], "test-corr-id")
        self.assertEqual(data["actor_id"], "test-actor")
        self.assertEqual(data["latency_ms"], 42)
        self.assertEqual(data["idempotency_key"], "VOL100")
        self.assertEqual(data["outcome_detail"], "test detail")

    def test_batch_parser_output_contains_canonical_and_legacy_keys(self):
        """Verify output dictionary entries contain both 'dna' and 'dna_sequence' keys."""
        test_dir = tempfile.mkdtemp()
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

        rule_file = os.path.join(rules_dir, 'rules_Volume.json')
        with open(rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        old_cwd = os.getcwd()
        os.chdir(test_dir)
        try:
            run_batch()
            json_out = os.path.join(output_dir, 'toSequence_parsed.json')
            with open(json_out, 'r') as f:
                records = json.load(f)
            self.assertEqual(len(records), 1)
            self.assertIn('dna', records[0])
            self.assertIn('dna_sequence', records[0])
            self.assertEqual(records[0]['dna'], "VOL08900750712")
            self.assertEqual(records[0]['dna_sequence'], "VOL08900750712")
        finally:
            os.chdir(old_cwd)
            shutil.rmtree(test_dir)

if __name__ == '__main__':
    unittest.main()
