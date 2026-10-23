import unittest
import os
import json
import tempfile
import shutil
from unittest.mock import patch

from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    RuleLoadError,
    InputReadError,
    PersistenceError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError,
    log_structured,
    run_batch
)


class TestMaintainabilityAndSignal(unittest.TestCase):
    def test_dna_status_enum_lowercase(self):
        """Verify that DNAStatus enum values are strictly lowercase strings."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_exception_taxonomy(self):
        """Verify exception taxonomy hierarchy."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_structured_log_schema(self):
        """Verify that log_structured includes all standard telemetry keys."""
        log_data = log_structured(
            correlation_id="test-corr-id-123",
            chain_name="dna_batch_parser",
            step="parse_sequence",
            outcome=DNAStatus.SUCCESS.value,
            latency_ms=12.34,
            actor_id="test_actor",
            idempotency_key="V100",
            outcome_detail="Parsed test"
        )
        required_keys = {
            "timestamp",
            "correlation_id",
            "actor_id",
            "chain_name",
            "step",
            "outcome",
            "latency_ms",
            "idempotency_key",
            "outcome_detail"
        }
        self.assertTrue(required_keys.issubset(set(log_data.keys())))
        self.assertEqual(log_data["correlation_id"], "test-corr-id-123")
        self.assertEqual(log_data["chain_name"], "dna_batch_parser")
        self.assertEqual(log_data["outcome"], "success")

    def test_canonical_and_legacy_naming_in_parsed_output(self):
        """Verify outputs contain both canonical 'dna_sequence' and legacy 'dna' keys."""
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
                f.write("V100\n")

            rule_file = os.path.join(rules_dir, 'rules_Volume.json')
            with open(rule_file, 'w') as f:
                json.dump({
                    "variable": "Volume",
                    "prefix": "V",
                    "subvars": {
                        "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                    }
                }, f)

            old_cwd = os.getcwd()
            os.chdir(test_dir)
            try:
                run_batch(correlation_id="test-run", actor_id="maintainability_test")
            finally:
                os.chdir(old_cwd)

            json_out = os.path.join(output_dir, 'toSequence_parsed.json')
            self.assertTrue(os.path.exists(json_out))

            with open(json_out, 'r') as f:
                data = json.load(f)
                self.assertEqual(len(data), 1)
                item = data[0]
                self.assertIn('dna_sequence', item)
                self.assertIn('dna', item)
                self.assertEqual(item['dna_sequence'], 'V100')
                self.assertEqual(item['dna'], 'V100')
        finally:
            shutil.rmtree(test_dir)


if __name__ == '__main__':
    unittest.main()
