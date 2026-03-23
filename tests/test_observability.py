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

    def test_observability_logs_format(self):
        # DNA for Volume
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test_cid_obs", actor_id="test_actor_obs")

        output = f.getvalue()
        obs_logs = [line for line in output.split('\n') if line.startswith('[OBSERVABILITY]')]

        self.assertGreater(len(obs_logs), 0, "No observability logs found")

        # Check one log entry for expected fields
        for log_line in obs_logs:
            json_str = log_line.replace('[OBSERVABILITY] ', '')
            log_data = json.loads(json_str)

            required_fields = [
                "timestamp", "correlation_id", "actor_id",
                "chain_name", "step", "outcome", "latency_ms"
            ]
            for field in required_fields:
                self.assertIn(field, log_data, f"Missing field {field} in log: {log_data}")

            self.assertEqual(log_data["correlation_id"], "test_cid_obs")
            self.assertEqual(log_data["actor_id"], "test_actor_obs")
            self.assertEqual(log_data["chain_name"], "dna_batch_chain")

        # Verify specific step and outcome for processing
        process_logs = [l for l in obs_logs if '"step": "process_dna"' in l]
        self.assertEqual(len(process_logs), 1)
        process_data = json.loads(process_logs[0].replace('[OBSERVABILITY] ', ''))
        self.assertEqual(process_data["outcome"], "SUCCESS")
        self.assertEqual(process_data["idempotency_key"], dna)

if __name__ == '__main__':
    unittest.main()
