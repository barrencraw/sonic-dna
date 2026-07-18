import os
import json
import shutil
import unittest
import time
from utils.dna_ui import main as run_batch

class TestIdempotency(unittest.TestCase):
    def setUp(self):
        # Setup paths
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        # Backup existing data if any
        self.backup_folder = os.path.join(self.project_root, 'data_backup')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        # Ensure clean state for test
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Initialize empty ledger
        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)

    def tearDown(self):
        # Restore backup
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            # Check if backup exists before moving
            if os.path.exists(self.backup_folder):
                shutil.move(self.backup_folder, self.data_folder)

    def test_double_invocation_same_key(self):
        # DNA for Volume (prefix 'VOL')
        dna = "VOL08900750712"

        # 1. First invocation
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['dna'], dna)

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertIn(dna, ledger)
        self.assertEqual(ledger[dna]['terminal_outcome'], 'success')

        # 2. Second invocation with same DNA
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        # Verify no duplicate entry in output
        with open(self.json_output, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1, "Should NOT have added a second entry for the same DNA")

    def test_mixed_duplicates(self):
        dna1 = "VOL08900750712"
        dna2 = "VOL00000000000"

        with open(self.input_file, 'w') as f:
            f.write(f"{dna1}\n{dna1}\n{dna2}\n")

        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)
        # It should process dna1 (once) and dna2 (once)
        self.assertEqual(len(data), 2, "Should have exactly 2 entries")
        dnas = [entry['dna'] for entry in data]
        self.assertIn(dna1, dnas)
        self.assertIn(dna2, dnas)

    def test_retry_after_transient_failure(self):
        # We'll simulate a transient failure by corrupting the output after a successful process
        # and then re-running.
        dna = "VOL08900750712"

        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch() # Success

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertIn(dna, ledger)

        # Simulate a crash where the output file was lost but ledger remained (or vice-versa)
        # If output file is lost, next run should NOT re-process if it's in the ledger.
        # WAIT: The requirement is "retry after transient failure → eventual consistency without corruption".
        # If the output file is cumulative and we lose it, but keep the ledger, we might miss the data.
        # But idempotency usually means "don't do it again if you already did it".

        # Let's test if it handles corrupted output file gracefully.
        with open(self.json_output, 'w') as f:
            f.write("CORRUPTED")

        new_dna = "VOL00000000000"
        with open(self.input_file, 'w') as f:
            f.write(new_dna + "\n")

        run_batch() # This should load the corrupted file, reset it to [], and add the new_dna

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        # Since VOL08900750712 was in the ledger, it was NOT re-processed.
        # Only VOL00000000000 is in the new output.
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['dna'], new_dna)

    def test_structured_telemetry_logs(self):
        # Patch standard print to capture the output logs
        from io import StringIO
        import sys

        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        saved_stdout = sys.stdout
        sys.stdout = out = StringIO()
        try:
            run_batch(correlation_id="test-corr-id-12345")
        finally:
            sys.stdout = saved_stdout

        output = out.getvalue()
        log_lines = [line for line in output.split('\n') if line.startswith("JSON_LOG:")]
        self.assertTrue(len(log_lines) >= 3, "Should log at least start_batch, process_sequence, and end_batch")

        # Parse and check fields of the logs
        logs = []
        for line in log_lines:
            json_part = line.replace("JSON_LOG:", "").strip()
            logs.append(json.loads(json_part))

        # Check start_batch
        start_log = logs[0]
        self.assertEqual(start_log['step'], "start_batch")
        self.assertEqual(start_log['correlation_id'], "test-corr-id-12345")
        self.assertEqual(start_log['chain_name'], "dna_batch_parsing")
        self.assertEqual(start_log['outcome'], "success")
        self.assertIn("timestamp", start_log)

        # Check process_sequence
        proc_log = logs[1]
        self.assertEqual(proc_log['step'], "process_sequence")
        self.assertEqual(proc_log['correlation_id'], "test-corr-id-12345")
        self.assertEqual(proc_log['idempotency_key'], dna)
        self.assertEqual(proc_log['outcome'], "success")

        # Check end_batch
        end_log = logs[-1]
        self.assertEqual(end_log['step'], "end_batch")
        self.assertEqual(end_log['correlation_id'], "test-corr-id-12345")
        self.assertEqual(end_log['outcome'], "success")

if __name__ == '__main__':
    unittest.main()
