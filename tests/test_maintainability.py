import unittest
import os
import json
import io
import sys
import tempfile
import shutil
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
    run_batch
)

class TestMaintainability(unittest.TestCase):

    def test_dna_status_values(self):
        """Verify explicit terminal states are lower-case canonical strings."""
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")
        self.assertEqual(DNAStatus.REFUSED, "refused")

    def test_exception_taxonomy(self):
        """Verify typed error inheritance hierarchy."""
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_structured_log_schema(self):
        """Verify log_structured outputs JSON_LOG: with required schema keys."""
        captured_output = io.StringIO()
        sys.stdout = captured_output
        try:
            log_structured(
                correlation_id="test-corr-123",
                actor_id="test_actor",
                chain_name="test_chain",
                step="test_step",
                outcome=DNAStatus.SUCCESS,
                latency_ms=12.34,
                idempotency_key="VOL100",
                outcome_detail="Passed test"
            )
        finally:
            sys.stdout = sys.__stdout__

        log_line = captured_output.getvalue().strip()
        self.assertTrue(log_line.startswith("JSON_LOG: "))

        json_str = log_line[len("JSON_LOG: "):]
        log_data = json.loads(json_str)

        required_keys = {
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        }
        self.assertTrue(required_keys.issubset(set(log_data.keys())))
        self.assertEqual(log_data["correlation_id"], "test-corr-123")
        self.assertEqual(log_data["actor_id"], "test_actor")
        self.assertEqual(log_data["chain_name"], "test_chain")
        self.assertEqual(log_data["step"], "test_step")
        self.assertEqual(log_data["outcome"], "success")

    def test_naming_alignment_and_output_keys(self):
        """Verify naming alignment 'dna_sequence' in DNACalculator and output entries."""
        calc = DNACalculator(rules_folder='rules')
        # Check method signature accepts parameter
        import inspect
        sig = inspect.signature(calc.parse)
        self.assertIn('dna_sequence', sig.parameters)

        test_dir = tempfile.mkdtemp()
        try:
            data_dir = os.path.join(test_dir, 'data')
            raw_dir = os.path.join(data_dir, 'raw')
            output_dir = os.path.join(data_dir, 'output')
            rules_dir = os.path.join(test_dir, 'rules')
            os.makedirs(raw_dir)
            os.makedirs(output_dir)
            os.makedirs(rules_dir)

            # Copy real rule files
            for item in os.listdir('rules'):
                if item.endswith('.json'):
                    shutil.copy(os.path.join('rules', item), rules_dir)

            with open(os.path.join(raw_dir, 'toSequence.txt'), 'w') as f:
                f.write("VOL08900750712\n")

            old_cwd = os.getcwd()
            os.chdir(test_dir)
            try:
                run_batch(correlation_id="test-corr", actor_id="test_runner")
                json_out = os.path.join(output_dir, 'toSequence_parsed.json')
                with open(json_out, 'r') as jf:
                    parsed = json.load(jf)
                self.assertEqual(len(parsed), 1)
                # Verify canonical 'dna_sequence' key alongside legacy 'dna' key
                self.assertIn('dna_sequence', parsed[0])
                self.assertIn('dna', parsed[0])
                self.assertEqual(parsed[0]['dna_sequence'], "VOL08900750712")
            finally:
                os.chdir(old_cwd)
        finally:
            shutil.rmtree(test_dir)

if __name__ == '__main__':
    unittest.main()
