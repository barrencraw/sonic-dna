import os
import json
import shutil
import unittest
import subprocess
import re

class TestObservability(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')

        # Ensure clean state
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)

    def test_observability_logs(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # Run main.py --once and capture output
        cmd = ["python3", "main.py", "--once"]
        result = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, "PYTHONPATH": "."})

        output = result.stdout
        # Find observability logs
        obs_logs = [line for line in output.splitlines() if line.startswith("[OBSERVABILITY]")]

        self.assertGreaterEqual(len(obs_logs), 3, "Should have at least batch_start, process_dna, and batch_finish logs")

        # Check process_dna log
        process_log_str = next(l for l in obs_logs if '"step": "process_dna"' in l)
        process_log = json.loads(process_log_str.replace("[OBSERVABILITY] ", ""))

        required_fields = ["timestamp", "correlation_id", "actor_id", "chain_name", "step", "outcome", "latency_ms", "idempotency_key"]
        for field in required_fields:
            self.assertIn(field, process_log, f"Missing field {field} in observability log")

        self.assertEqual(process_log["outcome"], "SUCCESS")
        self.assertEqual(process_log["actor_id"], "once_runner")
        self.assertEqual(process_log["chain_name"], "dna_batch_chain")
        self.assertEqual(process_log["idempotency_key"], dna)

if __name__ == '__main__':
    unittest.main()
