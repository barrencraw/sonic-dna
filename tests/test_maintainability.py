import os
import sys
import json
import shutil
import tempfile
import unittest
import io
from contextlib import redirect_stdout

from utils.dna_ui import (
    main as run_batch,
    DNAStatus,
    DNAProcessingError,
    InputReadError,
    RuleLoadError,
    PersistenceError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError,
    log_structured
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
            f.write("VOL08900750712\n")

        # Mock Volume rule file
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

    def test_naming_alignment_canonical_and_legacy_keys(self):
        """Verify output entries contain canonical 'dna_sequence' and backward-compatible 'dna'."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            run_batch(correlation_id="test-corr-123")

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertTrue(os.path.exists(json_out))

        with open(json_out, 'r', encoding='utf-8') as f:
            data = json.load(f)

        self.assertEqual(len(data), 1)
        entry = data[0]
        self.assertIn('dna_sequence', entry)
        self.assertIn('dna', entry)
        self.assertEqual(entry['dna_sequence'], 'VOL08900750712')
        self.assertEqual(entry['dna'], 'VOL08900750712')

    def test_dnastatus_enum_properties(self):
        """Verify DNAStatus string values match requirements for backward compatibility."""
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")
        self.assertEqual(DNAStatus.REFUSED, "refused")

    def test_typed_exception_taxonomy(self):
        """Verify exception inheritance tree."""
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

        # Test raising InputReadError when file missing
        os.remove(self.input_file)
        with self.assertRaises(InputReadError):
            run_batch()

    def test_structured_logging_schema(self):
        """Verify structured logs are emitted with required keys and prefix JSON_LOG:."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            log_structured(
                correlation_id="test-corr-456",
                actor_id="test_actor",
                chain_name="dna_batch_processing",
                step="parse_sequence",
                outcome=DNAStatus.SUCCESS,
                latency_ms=12.34,
                idempotency_key="VOL08900750712",
                outcome_detail={"rule": "Volume"}
            )

        output = buf.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG:"))

        json_str = output[len("JSON_LOG:"):]
        log_data = json.loads(json_str)

        required_keys = [
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        ]
        for key in required_keys:
            self.assertIn(key, log_data, f"Missing required log key: {key}")

        self.assertEqual(log_data["correlation_id"], "test-corr-456")
        self.assertEqual(log_data["actor_id"], "test_actor")
        self.assertEqual(log_data["chain_name"], "dna_batch_processing")
        self.assertEqual(log_data["step"], "parse_sequence")
        self.assertEqual(log_data["outcome"], "success")

if __name__ == '__main__':
    unittest.main()
