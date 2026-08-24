import os
import json
import inspect
import tempfile
import unittest
from utils.dna_calculator import DNACalculator
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
    run_batch
)


class TestMaintainabilityAndSignal(unittest.TestCase):

    def test_naming_alignment_dna_calculator(self):
        """Verify DNACalculator.parse inspects signature uses canonical 'dna_sequence'."""
        sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', sig.parameters, "DNACalculator.parse must use 'dna_sequence' parameter name")

    def test_exception_taxonomy_hierarchy(self):
        """Verify explicit exception class hierarchy."""
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_corrupted_ledger_raises_typed_error(self):
        """Verify load_ledger raises typed LedgerLoadError when reading corrupted JSON."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
            tmp.write("{ invalid json content ...")
            tmp_path = tmp.name

        try:
            with self.assertRaises(LedgerLoadError):
                load_ledger(tmp_path)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_dna_status_enum_values(self):
        """Verify DNAStatus enum string values match explicit terminal state expectations."""
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")
        self.assertEqual(DNAStatus.REFUSED, "refused")

    def test_structured_logging_schema(self):
        """Verify log_structured outputs schema-compliant telemetry entry."""
        correlation_id = "test-corr-id-1234"
        actor_id = "test_actor"
        chain_name = "test_chain"
        step = "test_step"
        outcome = DNAStatus.SUCCESS
        latency_ms = 12.34
        idempotency_key = "VOL08900750712"
        outcome_detail = "Test execution completed"

        entry = log_structured(
            correlation_id=correlation_id,
            actor_id=actor_id,
            chain_name=chain_name,
            step=step,
            outcome=outcome,
            latency_ms=latency_ms,
            idempotency_key=idempotency_key,
            outcome_detail=outcome_detail
        )

        required_keys = {
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        }
        self.assertTrue(required_keys.issubset(entry.keys()), f"Missing keys in log schema: {required_keys - set(entry.keys())}")
        self.assertEqual(entry["correlation_id"], correlation_id)
        self.assertEqual(entry["actor_id"], actor_id)
        self.assertEqual(entry["chain_name"], chain_name)
        self.assertEqual(entry["step"], step)
        self.assertEqual(entry["outcome"], "success")
        self.assertEqual(entry["idempotency_key"], idempotency_key)

    def test_parsed_output_contains_canonical_key(self):
        """Verify batch parsed output includes canonical 'dna_sequence' and legacy 'dna' keys."""
        test_dir = tempfile.mkdtemp()
        raw_dir = os.path.join(test_dir, 'data', 'raw')
        output_dir = os.path.join(test_dir, 'data', 'output')
        rules_dir = os.path.join(test_dir, 'rules')
        os.makedirs(raw_dir)
        os.makedirs(output_dir)
        os.makedirs(rules_dir)

        # Rule for Volume
        rule_file = os.path.join(rules_dir, 'rules_Volume.json')
        with open(rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        input_file = os.path.join(raw_dir, 'toSequence.txt')
        with open(input_file, 'w') as f:
            f.write("VOL100\n")

        old_cwd = os.getcwd()
        os.chdir(test_dir)
        try:
            run_batch(correlation_id="test-run", actor_id="test_runner")
            json_out = os.path.join(output_dir, 'toSequence_parsed.json')
            self.assertTrue(os.path.exists(json_out))
            with open(json_out, 'r') as f:
                data = json.load(f)
                self.assertEqual(len(data), 1)
                self.assertIn('dna_sequence', data[0])
                self.assertIn('dna', data[0])
                self.assertEqual(data[0]['dna_sequence'], 'VOL100')
                self.assertEqual(data[0]['dna'], 'VOL100')
        finally:
            os.chdir(old_cwd)


if __name__ == '__main__':
    unittest.main()
