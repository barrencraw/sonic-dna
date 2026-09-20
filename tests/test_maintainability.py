import os
import io
import json
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from utils.dna_calculator import DNACalculator, Rule
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
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("VOL0890075071\n")

        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w', encoding='utf-8') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3},
                    "pan": {"description": "panning", "min": 0, "max": 999, "pad": 3},
                    "curve": {"description": "fade curve", "min": 0, "max": 999, "pad": 3},
                    "mute": {"description": "mute flag", "min": 0, "max": 9, "pad": 1}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_naming_alignment_and_backward_compatibility(self):
        """Verify dna_sequence parameter in API and dual keys in JSON output."""
        calc = DNACalculator(rules_folder=self.rules_dir)
        res = calc.parse("VOL0890075071")
        self.assertEqual(res['rule'], "Volume")

        run_batch(correlation_id="test-corr-1", actor_id="test_actor")

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertTrue(os.path.exists(json_out))

        with open(json_out, 'r', encoding='utf-8') as f:
            parsed = json.load(f)

        self.assertEqual(len(parsed), 1)
        # Canonical key presence
        self.assertIn('dna_sequence', parsed[0])
        # Legacy key presence for backward compatibility
        self.assertIn('dna', parsed[0])
        self.assertEqual(parsed[0]['dna_sequence'], "VOL0890075071")
        self.assertEqual(parsed[0]['dna'], "VOL0890075071")

    def test_dna_status_enum_values(self):
        """Verify DNAStatus enum defines canonical lowercase string outcomes."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_typed_exception_hierarchy(self):
        """Verify typed exceptions subclass appropriate base classes."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_structured_logging_schema(self):
        """Verify structured log utility emits JSON_LOG: prefix with required schema fields."""
        stdout_buf = io.StringIO()
        with patch('sys.stdout', stdout_buf):
            log_structured(
                correlation_id="corr-123",
                actor_id="test_actor",
                chain_name="test_chain",
                step="test_step",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=12.34,
                idempotency_key="key-456",
                outcome_detail="detail info"
            )

        out = stdout_buf.getvalue().strip()
        self.assertTrue(out.startswith("JSON_LOG: "))

        log_json = out[len("JSON_LOG: "):]
        payload = json.loads(log_json)

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
            self.assertIn(field, payload)

        self.assertEqual(payload["correlation_id"], "corr-123")
        self.assertEqual(payload["actor_id"], "test_actor")
        self.assertEqual(payload["chain_name"], "test_chain")
        self.assertEqual(payload["step"], "test_step")
        self.assertEqual(payload["outcome"], "success")
        self.assertEqual(payload["idempotency_key"], "key-456")

if __name__ == '__main__':
    unittest.main()
