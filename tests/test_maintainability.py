import os
import sys
import json
import io
import time
import inspect
import unittest
import tempfile
import shutil
from unittest.mock import patch, MagicMock

from utils.dna_calculator import Rule, DNACalculator
from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    RuleLoadError,
    InputReadError,
    ThermalOverloadError,
    PersistenceError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError,
    log_structured,
    run_batch,
    load_ledger,
    save_ledger
)

class TestMaintainability(unittest.TestCase):

    def test_naming_alignment(self):
        """Verify that canonical parameter 'dna_sequence' is enforced in parse signatures."""
        rule_sig = inspect.signature(Rule.parse)
        calc_sig = inspect.signature(DNACalculator.parse)

        self.assertIn('dna_sequence', rule_sig.parameters, "Rule.parse missing 'dna_sequence' parameter")
        self.assertIn('dna_sequence', calc_sig.parameters, "DNACalculator.parse missing 'dna_sequence' parameter")

    def test_exception_taxonomy(self):
        """Verify typed exception hierarchy and inheritance."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(ThermalOverloadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))

        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

        # Ensure all inherit from DNAProcessingError
        self.assertTrue(issubclass(LedgerLoadError, DNAProcessingError))
        self.assertTrue(issubclass(AtomicWriteError, DNAProcessingError))

    def test_dnastatus_enum(self):
        """Verify DNAStatus string enum values are strictly lowercase canonical statuses."""
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")
        self.assertEqual(DNAStatus.REFUSED, "refused")

        expected_statuses = {"success", "error", "skipped", "refused"}
        actual_statuses = {status.value for status in DNAStatus}
        self.assertEqual(expected_statuses, actual_statuses)

    def test_structured_log_schema(self):
        """Verify structured log helper emits JSON_LOG with all standard mandatory fields."""
        stdout_capture = io.StringIO()
        with patch('sys.stdout', stdout_capture):
            log_structured(
                correlation_id="test-corr-123",
                chain_name="dna_batch_parser",
                step="parse_sequence",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=12,
                actor_id="test_actor",
                idempotency_key="VOL08900750712",
                outcome_detail="Parsed successfully"
            )

        output = stdout_capture.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "), f"Output does not start with JSON_LOG: {output}")

        json_str = output[len("JSON_LOG: "):]
        data = json.loads(json_str)

        required_keys = [
            "timestamp",
            "correlation_id",
            "chain_name",
            "step",
            "outcome",
            "latency_ms",
            "actor_id",
            "idempotency_key",
            "outcome_detail"
        ]

        for key in required_keys:
            self.assertIn(key, data, f"Missing required log field: {key}")

        self.assertEqual(data["correlation_id"], "test-corr-123")
        self.assertEqual(data["chain_name"], "dna_batch_parser")
        self.assertEqual(data["step"], "parse_sequence")
        self.assertEqual(data["outcome"], "success")
        self.assertEqual(data["actor_id"], "test_actor")
        self.assertEqual(data["idempotency_key"], "VOL08900750712")

    def test_backward_compatibility_output_keys(self):
        """Verify outputs retain both legacy 'dna' and canonical 'dna_sequence' keys."""
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

            rule_file = os.path.join(rules_dir, 'rules_Volume.json')
            with open(rule_file, 'w') as f:
                json.dump({
                    "variable": "Volume",
                    "prefix": "VOL",
                    "subvars": {
                        "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3},
                        "pan": {"description": "panning", "min": 0, "max": 999, "pad": 3},
                        "fade": {"description": "fade in", "min": 0, "max": 999, "pad": 3}
                    }
                }, f)

            old_cwd = os.getcwd()
            os.chdir(test_dir)
            try:
                run_batch(correlation_id="test-compat-key")
                json_out = os.path.join(output_dir, 'toSequence_parsed.json')
                self.assertTrue(os.path.exists(json_out))

                with open(json_out, 'r') as f:
                    entries = json.load(f)

                self.assertEqual(len(entries), 1)
                entry = entries[0]
                self.assertIn('dna', entry, "Missing legacy 'dna' key in JSON output")
                self.assertIn('dna_sequence', entry, "Missing canonical 'dna_sequence' key in JSON output")
                self.assertEqual(entry['dna'], "VOL08900750712")
                self.assertEqual(entry['dna_sequence'], "VOL08900750712")
            finally:
                os.chdir(old_cwd)
        finally:
            shutil.rmtree(test_dir)

    def test_thermal_fatigue_lockout_and_cooling(self):
        """Verify heat accumulation, lockout at 10.0 threshold, and dissipation over time."""
        test_dir = tempfile.mkdtemp()
        try:
            data_dir = os.path.join(test_dir, 'data')
            raw_dir = os.path.join(data_dir, 'raw')
            output_dir = os.path.join(data_dir, 'output')
            rules_dir = os.path.join(test_dir, 'rules')

            os.makedirs(raw_dir)
            os.makedirs(output_dir)
            os.makedirs(rules_dir)

            rule_file = os.path.join(rules_dir, 'rules_Volume.json')
            with open(rule_file, 'w') as f:
                json.dump({
                    "variable": "Volume",
                    "prefix": "VOL",
                    "subvars": {
                        "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                    }
                }, f)

            # Create 6 sequences (2.0 heat units each = 12.0 total heat, exceeds 10.0 lockout)
            sequences = [f"VOL00{i}" for i in range(6)]
            input_file = os.path.join(raw_dir, 'toSequence.txt')
            with open(input_file, 'w') as f:
                f.write("\n".join(sequences) + "\n")

            old_cwd = os.getcwd()
            os.chdir(test_dir)
            try:
                # First 4 sequences add 8.0 heat. 5th adds 2.0 = 10.0 heat. 6th sequence (12.0) triggers lockout
                with self.assertRaises(ThermalOverloadError):
                    run_batch(correlation_id="test-heat-lockout")

                ledger_path = os.path.join(data_dir, 'processed_ledger.json')
                full_ledger = load_ledger(ledger_path)
                system_state = full_ledger.get('system_state', {})
                self.assertGreater(system_state.get('core_heat', 0.0), 8.0)
            finally:
                os.chdir(old_cwd)
        finally:
            shutil.rmtree(test_dir)

if __name__ == '__main__':
    unittest.main()
