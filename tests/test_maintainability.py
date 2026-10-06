import os
import io
import sys
import json
import tempfile
import shutil
import unittest
from unittest.mock import patch

from utils.dna_ui import (
    run_batch,
    log_structured,
    DNAStatus,
    DNAProcessingError,
    RuleLoadError,
    InputReadError,
    PersistenceError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError
)


class TestMaintainabilityAndSignal(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.rules_dir, exist_ok=True)

        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w', encoding='utf-8') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_dna_status_enum_values(self):
        """Verify explicit lowercase terminal states for backward compatibility and clean schema."""
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")
        self.assertEqual(DNAStatus.REFUSED, "refused")

    def test_error_taxonomy_inheritance(self):
        """Verify typed error classification hierarchy."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_structured_log_field_presence(self):
        """Verify structured logs contain all mandatory keys."""
        captured_output = io.StringIO()
        with patch('sys.stdout', captured_output):
            log_structured(
                correlation_id="test-corr-id-123",
                actor_id="test_actor",
                chain_name="dna_batch_parser",
                step="test_step",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=12.34,
                idempotency_key="VOL100",
                outcome_detail="test_detail"
            )

        output_str = captured_output.getvalue().strip()
        self.assertTrue(output_str.startswith("JSON_LOG:"))

        json_str = output_str.replace("JSON_LOG:", "").strip()
        payload = json.loads(json_str)

        required_keys = [
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        ]
        for key in required_keys:
            self.assertIn(key, payload)

        self.assertEqual(payload["correlation_id"], "test-corr-id-123")
        self.assertEqual(payload["actor_id"], "test_actor")
        self.assertEqual(payload["chain_name"], "dna_batch_parser")
        self.assertEqual(payload["outcome"], "success")

    def test_canonical_naming_and_dto_schema(self):
        """Verify output JSON contains both canonical 'dna_sequence' and legacy 'dna' keys."""
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("VOL100\n")

        run_batch(correlation_id="corr-test-1", actor_id="maintainability_test")

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertTrue(os.path.exists(json_out))

        with open(json_out, 'r', encoding='utf-8') as f:
            data = json.load(f)

        self.assertEqual(len(data), 1)
        self.assertIn('dna_sequence', data[0])
        self.assertIn('dna', data[0])
        self.assertEqual(data[0]['dna_sequence'], 'VOL100')
        self.assertEqual(data[0]['dna'], 'VOL100')

    def test_corrupt_ledger_raises_typed_exception(self):
        """Verify corrupt ledger file triggers explicit LedgerLoadError."""
        ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')
        with open(ledger_path, 'w', encoding='utf-8') as f:
            f.write("{invalid json content")

        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("VOL100\n")

        with self.assertRaises(LedgerLoadError):
            run_batch()


if __name__ == '__main__':
    unittest.main()
