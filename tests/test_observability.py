import os
import json
import shutil
import unittest
import io
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch

class TestObservability(unittest.TestCase):
    def setUp(self):
        # Setup paths
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        # Backup existing data if any
        self.backup_folder = os.path.join(self.project_root, 'data_backup_obs')
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
            shutil.move(self.backup_folder, self.data_folder)

    def test_structured_logging_fields(self):
        # DNA for Volume (prefix 'VOL')
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-corr-id", actor_id="test-actor")

        output = f.getvalue()
        obs_logs = [line for line in output.split('\n') if line.startswith('[OBSERVABILITY]')]

        self.assertGreater(len(obs_logs), 0, "Should have emitted at least one observability log")

        # Verify the structure of the logs
        for log_line in obs_logs:
            json_str = log_line.replace('[OBSERVABILITY] ', '')
            log_entry = json.loads(json_str)

            required_fields = ["correlation_id", "actor_id", "chain_name", "step", "outcome", "timestamp"]
            for field in required_fields:
                self.assertIn(field, log_entry, f"Log entry missing required field: {field}")

            self.assertEqual(log_entry["correlation_id"], "test-corr-id")
            self.assertEqual(log_entry["actor_id"], "test-actor")
            self.assertEqual(log_entry["chain_name"], "dna_batch_chain")

        # Verify specific steps exist
        steps = [json.loads(line.replace('[OBSERVABILITY] ', ''))["step"] for line in obs_logs]
        self.assertIn("start_batch", steps)
        self.assertIn("process_dna", steps)
        self.assertIn("complete_batch", steps)

if __name__ == '__main__':
    unittest.main()
