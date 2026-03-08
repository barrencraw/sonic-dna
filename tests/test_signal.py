import unittest
import json
import io
import contextlib
import os
import shutil
from utils.dna_ui import main as run_batch, DNAProcessingOutcome

class TestSignal(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')

        # Backup and clear
        self.backup_folder = os.path.join(self.project_root, 'data_backup_signal')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_observability_log_format(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            run_batch(correlation_id="test-correlation-id")

        output = f.getvalue()
        logs = [line for line in output.split('\n') if line.startswith("[OBSERVABILITY]")]

        self.assertTrue(len(logs) >= 3, "Should have at least start, process_item, and complete logs")

        # Check start log
        start_log = json.loads(logs[0].replace("[OBSERVABILITY] ", ""))
        self.assertEqual(start_log['correlation_id'], "test-correlation-id")
        self.assertEqual(start_log['step'], "start")
        self.assertEqual(start_log['outcome'], "processing")

        # Check item log
        item_log = json.loads(logs[1].replace("[OBSERVABILITY] ", ""))
        self.assertEqual(item_log['correlation_id'], "test-correlation-id")
        self.assertEqual(item_log['step'], "process_item")
        self.assertEqual(item_log['outcome'], DNAProcessingOutcome.SUCCESS.value)
        self.assertEqual(item_log['idempotency_key'], dna)
        self.assertIn('latency_ms', item_log)

if __name__ == '__main__':
    unittest.main()
