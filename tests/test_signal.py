import os
import json
import shutil
import unittest
import io
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch

class TestSignal(unittest.TestCase):
    def setUp(self):
        # Setup paths
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        # Backup existing data
        self.backup_folder = os.path.join(self.project_root, 'data_backup_signal')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)

    def tearDown(self):
        # Restore backup
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_observability_signal(self):
        # DNA for Volume
        dna = "VOL08900750712"
        correlation_id = "test-correlation-id"

        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id=correlation_id)

        output = f.getvalue()
        logs = [line for line in output.split('\n') if "[OBSERVABILITY]" in line]

        # Verify start log
        start_log = json.loads(logs[0].replace("[OBSERVABILITY] ", ""))
        self.assertEqual(start_log['correlation_id'], correlation_id)
        self.assertEqual(start_log['step'], 'start')

        # Verify step log
        step_log = json.loads(logs[1].replace("[OBSERVABILITY] ", ""))
        self.assertEqual(step_log['idempotency_key'], dna)
        self.assertEqual(step_log['outcome'], 'SUCCESS')

        # Verify terminal log
        terminal_log = json.loads(logs[-1].replace("[OBSERVABILITY] ", ""))
        self.assertEqual(terminal_log['outcome'], 'SUCCESS')
        self.assertEqual(terminal_log['new_processed'], 1)
        self.assertIn('latency_ms', terminal_log)

    def test_idempotency_dedupe_signal(self):
        dna = "VOL08900750712"
        correlation_id_1 = "cid-1"
        correlation_id_2 = "cid-2"

        # First run
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")
        run_batch(correlation_id=correlation_id_1)

        # Second run (dedupe)
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id=correlation_id_2)

        output = f.getvalue()
        logs = [line for line in output.split('\n') if "[OBSERVABILITY]" in line]

        # Verify DEDUPE outcome in logs
        found_dedupe = False
        for log_line in logs:
            data = json.loads(log_line.replace("[OBSERVABILITY] ", ""))
            if data.get('step') == 'process_string' and data.get('idempotency_key') == dna:
                self.assertEqual(data.get('outcome'), 'DEDUPE')
                found_dedupe = True
                break
        self.assertTrue(found_dedupe)

if __name__ == '__main__':
    unittest.main()
