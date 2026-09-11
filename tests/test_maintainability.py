import unittest
import os
import json
import io
import shutil
import tempfile
from contextlib import redirect_stdout
from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    InputReadError,
    RuleLoadError,
    PersistenceError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError,
    ThermalOverloadError,
    run_batch
)
from utils.dna_calculator import DNACalculator

class TestMaintainability(unittest.TestCase):
    def test_dna_status_enum_values(self):
        self.assertEqual(DNAStatus.SUCCESS.value, 'success')
        self.assertEqual(DNAStatus.ERROR.value, 'error')
        self.assertEqual(DNAStatus.SKIPPED.value, 'skipped')
        self.assertEqual(DNAStatus.REFUSED.value, 'refused')

    def test_exception_hierarchy(self):
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))
        self.assertTrue(issubclass(ThermalOverloadError, DNAProcessingError))

    def test_structured_log_format_and_keys(self):
        test_dir = tempfile.mkdtemp()
        old_cwd = os.getcwd()
        try:
            os.chdir(test_dir)
            os.makedirs('data/raw', exist_ok=True)
            os.makedirs('data/output', exist_ok=True)
            os.makedirs('rules', exist_ok=True)

            with open('data/raw/toSequence.txt', 'w') as f:
                f.write("VOL08900750712\n")

            with open('rules/rules_Volume.json', 'w') as f:
                json.dump({
                    "variable": "Volume",
                    "prefix": "VOL",
                    "subvars": {
                        "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3},
                        "gain": {"description": "gain level", "min": 0, "max": 999, "pad": 3},
                        "attenuation": {"description": "attenuation level", "min": 0, "max": 999, "pad": 3},
                        "trim": {"description": "trim level", "min": 0, "max": 99, "pad": 2}
                    }
                }, f)

            f_out = io.StringIO()
            with redirect_stdout(f_out):
                run_batch(correlation_id="test-corr-id-123", actor_id="test_actor")

            logs = [line for line in f_out.getvalue().splitlines() if line.startswith("JSON_LOG:")]
            self.assertGreater(len(logs), 0, "Expected structured logs with JSON_LOG: prefix")

            payload = json.loads(logs[0].replace("JSON_LOG:", "").strip())
            required_keys = [
                "timestamp", "correlation_id", "actor_id", "chain_name",
                "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
            ]
            for key in required_keys:
                self.assertIn(key, payload)

            self.assertEqual(payload["correlation_id"], "test-corr-id-123")
            self.assertEqual(payload["actor_id"], "test_actor")
            self.assertEqual(payload["chain_name"], "dna_batch_parser")

            with open('data/output/toSequence_parsed.json', 'r') as f:
                data = json.load(f)
                self.assertIn('dna', data[0])
                self.assertIn('dna_sequence', data[0])
                self.assertEqual(data[0]['dna'], data[0]['dna_sequence'])
        finally:
            os.chdir(old_cwd)
            shutil.rmtree(test_dir)

if __name__ == '__main__':
    unittest.main()
