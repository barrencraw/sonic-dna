import unittest
import os
import json
import shutil
import io
import contextlib
from utils.dna_ui import main as run_batch, TerminalOutcome

class TestMaintainability(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        # Backup existing data
        self.backup_folder = os.path.join(self.project_root, 'data_backup_maint')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_naming_alignment_and_structured_logs(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # Capture output to check structured logs
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            run_batch(correlation_id="test-cid")

        output = f.getvalue()

        # 1. Verify dna_sequence in output
        with open(self.json_output, 'r') as jf:
            data = json.load(jf)
        self.assertEqual(data[0]['dna_sequence'], dna, "Key should be 'dna_sequence'")
        self.assertNotIn('dna', data[0], "Legacy 'dna' key should not exist")

        # 2. Verify structured logs
        log_lines = [line for line in output.split('\n') if line.startswith('JSON_LOG:')]
        self.assertTrue(len(log_lines) >= 2, "Should have at least process_sequence and batch_complete logs")

        found_process = False
        for line in log_lines:
            log_data = json.loads(line[len('JSON_LOG: '):])
            self.assertEqual(log_data['correlation_id'], "test-cid")
            self.assertEqual(log_data['chain_name'], "dna_batch_chain")
            if log_data['step'] == "process_sequence":
                self.assertEqual(log_data['outcome'], TerminalOutcome.SUCCESS.value)
                self.assertEqual(log_data['idempotency_key'], dna)
                found_process = True

        self.assertTrue(found_process, "Should have found process_sequence log step")

    def test_terminal_outcome_in_ledger(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as lf:
            ledger = json.load(lf)

        self.assertIn(dna, ledger)
        self.assertEqual(ledger[dna]['terminal_outcome'], TerminalOutcome.SUCCESS.value)

    def test_parse_error_outcome(self):
        bad_dna = "INVALID_DNA"
        with open(self.input_file, 'w') as f:
            f.write(bad_dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as lf:
            ledger = json.load(lf)

        self.assertEqual(ledger[bad_dna]['terminal_outcome'], TerminalOutcome.PARSE_ERROR.value)

if __name__ == '__main__':
    unittest.main()
