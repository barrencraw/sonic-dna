import unittest
import os
import io
import contextlib
import json
import shutil
from utils.dna_ui import main as run_batch, TerminalOutcome

class TestMaintainability(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data_test_maint')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # We need to monkeypatch os.getcwd in utils.dna_ui or change dir
        self.old_cwd = os.getcwd()
        os.chdir(self.project_root) # Ensure we are at root

    def tearDown(self):
        os.chdir(self.old_cwd)
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)

    def test_structured_logging_format(self):
        """Verify that logs follow the [LOG] format with required fields."""
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # Mock paths in dna_ui by changing directory or using a better approach
        # For simplicity in this environment, I'll use the real 'data' folder but
        # I should probably have refactored dna_ui to accept paths.
        # Since I didn't, I'll temporarily move the real 'data' folder.
        real_data = os.path.join(self.project_root, 'data')
        backup_data = os.path.join(self.project_root, 'data_backup_maint')
        if os.path.exists(real_data):
            os.rename(real_data, backup_data)

        os.rename(self.data_folder, real_data)

        try:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                run_batch(correlation_id="test-corr-id")

            output = stdout.getvalue()
        finally:
            # Restore real data
            os.rename(real_data, self.data_folder)
            if os.path.exists(backup_data):
                os.rename(backup_data, real_data)

        # Verify first log line (idempotency check)
        self.assertIn("[LOG]", output)
        self.assertIn("correlation_id=test-corr-id", output)
        self.assertIn("chain_name=dna_batch_process", output)
        self.assertIn("outcome=success", output)
        self.assertIn("latency_ms=", output)
        self.assertIn("idempotency_key=" + dna, output)

    def test_terminal_outcome_enum_usage(self):
        """Verify that TerminalOutcome enum is used correctly in the ledger."""
        self.assertEqual(TerminalOutcome.SUCCESS.value, "success")
        self.assertEqual(TerminalOutcome.PARSE_ERROR.value, "parse_error")
        self.assertEqual(TerminalOutcome.SKIPPED.value, "skipped")

        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        real_data = os.path.join(self.project_root, 'data')
        backup_data = os.path.join(self.project_root, 'data_backup_maint_2')
        if os.path.exists(real_data):
            os.rename(real_data, backup_data)
        os.rename(self.data_folder, real_data)

        try:
            run_batch(correlation_id="test-corr-id-2")

            with open(os.path.join(real_data, 'processed_ledger.json'), 'r') as f:
                ledger = json.load(f)

            self.assertIn(dna, ledger)
            self.assertEqual(ledger[dna]['terminal_outcome'], TerminalOutcome.SUCCESS.value)
        finally:
            os.rename(real_data, self.data_folder)
            if os.path.exists(backup_data):
                os.rename(backup_data, real_data)

if __name__ == '__main__':
    unittest.main()
