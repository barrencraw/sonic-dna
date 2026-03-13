import os
import json
import unittest
import io
import contextlib
import uuid
from utils.dna_ui import main as run_batch

class TestSignal(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')

        os.makedirs(self.raw_folder, exist_ok=True)
        # Ensure input file exists
        with open(self.input_file, 'w') as f:
            f.write("VOL08900750712\n")

    def test_observability_logs(self):
        correlation_id = str(uuid.uuid4())
        actor_id = "test-actor"

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            run_batch(correlation_id=correlation_id, actor_id=actor_id)

        log_lines = [line for line in output.getvalue().split('\n') if line.startswith('[OBSERVABILITY]')]
        self.assertTrue(len(log_lines) >= 3, f"Expected at least 3 observability logs, got {len(log_lines)}")

        found_start = False
        found_process = False
        found_terminal = False

        for line in log_lines:
            json_str = line.replace('[OBSERVABILITY] ', '')
            data = json.loads(json_str)

            self.assertEqual(data['correlation_id'], correlation_id)
            self.assertEqual(data['actor_id'], actor_id)
            self.assertEqual(data['chain_name'], 'dna_batch_chain')
            self.assertIn('timestamp', data)
            self.assertIn('step', data)
            self.assertIn('outcome', data)

            if data['step'] == 'start':
                found_start = True
                self.assertEqual(data['outcome'], 'STARTED')
            elif data['step'] == 'process_dna':
                found_process = True
                self.assertIn('idempotency_key', data)
                self.assertIn('latency_ms', data)
            elif data['step'] == 'terminal':
                found_terminal = True
                self.assertEqual(data['outcome'], 'SUCCESS')
                self.assertIn('latency_ms', data)
                self.assertIn('new_processed', data)

        self.assertTrue(found_start, "Missing 'start' log step")
        self.assertTrue(found_process, "Missing 'process_dna' log step")
        self.assertTrue(found_terminal, "Missing 'terminal' log step")

if __name__ == '__main__':
    unittest.main()
