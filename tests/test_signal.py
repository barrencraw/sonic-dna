import unittest
import json
import os
import shutil
from io import StringIO
from unittest.mock import patch
from utils.dna_ui import main as run_batch, Outcome

class TestSignal(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')

        # Backup and clear data
        self.backup_folder = os.path.join(self.project_root, 'data_backup_signal')
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

    def test_structured_logging_presence(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        with patch('sys.stdout', new=StringIO()) as fake_out:
            run_batch(correlation_id="test-cid", actor_id="test-actor")
            output = fake_out.getvalue()

        # Check for [OBSERVABILITY] lines
        obs_lines = [line for line in output.split('\n') if line.startswith('[OBSERVABILITY]')]
        self.assertGreaterEqual(len(obs_lines), 3) # START, process_dna, END

        # Parse one line and verify fields
        found_process_dna = False
        for line in obs_lines:
            data = json.loads(line.replace('[OBSERVABILITY] ', ''))
            self.assertEqual(data['correlation_id'], "test-cid")
            self.assertEqual(data['actor_id'], "test-actor")
            self.assertIn('timestamp', data)
            self.assertIn('chain_name', data)
            self.assertIn('step', data)
            self.assertIn('outcome', data)

            if data['step'] == "process_dna":
                found_process_dna = True
                self.assertEqual(data['idempotency_key'], dna)
                self.assertEqual(data['outcome'], Outcome.SUCCESS.value)
                self.assertIn('latency_ms', data)

        self.assertTrue(found_process_dna)

    def test_error_logging(self):
        dna = "INVALID_DNA"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        with patch('sys.stdout', new=StringIO()) as fake_out:
            run_batch(correlation_id="error-cid", actor_id="error-actor")
            output = fake_out.getvalue()

        obs_lines = [line for line in output.split('\n') if line.startswith('[OBSERVABILITY]')]

        found_error = False
        for line in obs_lines:
            data = json.loads(line.replace('[OBSERVABILITY] ', ''))
            if data['step'] == "process_dna" and data['outcome'] == Outcome.ERROR.value:
                found_error = True
                self.assertIn('error', data)
                self.assertEqual(data['idempotency_key'], dna)

        self.assertTrue(found_error)

if __name__ == '__main__':
    unittest.main()
