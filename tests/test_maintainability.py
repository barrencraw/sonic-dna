import unittest
import inspect
import json
import os
import shutil
import tempfile
from utils.dna_calculator import DNACalculator
from utils.dna_ui import DNAStatus, main as run_batch

class TestMaintainability(unittest.TestCase):
    def test_canonical_naming_calculator(self):
        """Verify DNACalculator.parse uses 'dna_sequence' parameter."""
        sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', sig.parameters)

    def test_structured_logging_format(self, capsys=None):
        """
        Verify log_structured output contains mandatory fields.
        Note: We use a small integration test to capture stdout.
        """
        from utils.dna_ui import log_structured
        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with redirect_stdout(f):
            log_structured(
                step="test-step",
                outcome="success",
                correlation_id="test-corr",
                idempotency_key="test-key"
            )
        output = f.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "))
        log_data = json.loads(output[10:])

        mandatory_fields = [
            "timestamp", "correlation_id", "actor_id",
            "chain_name", "step", "outcome",
            "latency_ms", "idempotency_key"
        ]
        for field in mandatory_fields:
            self.assertIn(field, log_data, f"Missing mandatory field: {field}")

    def test_ledger_status_enum(self):
        """Verify that processed_ledger uses values from DNAStatus enum."""
        # Setup a temporary environment
        tmp_dir = tempfile.mkdtemp()
        try:
            data_dir = os.path.join(tmp_dir, 'data')
            raw_dir = os.path.join(data_dir, 'raw')
            output_dir = os.path.join(data_dir, 'output')
            os.makedirs(raw_dir)
            os.makedirs(output_dir)

            # Use rules from current project
            rules_dir = os.path.join(os.getcwd(), 'rules')

            # Create a simple input
            dna = "VOL08900750712"
            with open(os.path.join(raw_dir, 'toSequence.txt'), 'w') as f:
                f.write(dna + "\n")

            # Run batch in the temp dir context
            original_cwd = os.getcwd()
            os.chdir(tmp_dir)
            try:
                # Need to make sure rules are found.
                # DNACalculator by default looks in 'rules' relative to CWD or provided path.
                # In dna_ui.py it uses os.path.join(project_root, 'rules') where project_root = os.getcwd()
                # So we need to symlink or copy rules.
                os.symlink(rules_dir, os.path.join(tmp_dir, 'rules'))

                run_batch(correlation_id="test-guard")

                ledger_path = os.path.join(data_dir, 'processed_ledger.json')
                self.assertTrue(os.path.exists(ledger_path))
                with open(ledger_path, 'r') as f:
                    ledger = json.load(f)

                self.assertIn(dna, ledger)
                status = ledger[dna]['terminal_outcome']
                # Check if status is one of the DNAStatus values
                valid_statuses = [s.value for s in DNAStatus]
                self.assertIn(status, valid_statuses)

            finally:
                os.chdir(original_cwd)
        finally:
            shutil.rmtree(tmp_dir)

if __name__ == '__main__':
    unittest.main()
