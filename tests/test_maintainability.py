import unittest
import os
import shutil
import tempfile
import json
import io
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch

class TestMaintainability(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for tests
        self.test_dir = tempfile.mkdtemp()
        self.project_root = os.getcwd()

        # Setup data folders
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')

        # Change to test_dir so dna_ui finds the right paths
        os.chdir(self.test_dir)

        # Mock rules folder (copy from original)
        shutil.copytree(os.path.join(self.project_root, 'rules'), os.path.join(self.test_dir, 'rules'))

    def tearDown(self):
        os.chdir(self.project_root)
        shutil.rmtree(self.test_dir)

    def test_structured_logging(self):
        # Write some DNA strings to input file
        # VOL08900750712 is valid per rules/rules_Volume.json
        with open(self.input_file, 'w') as f:
            f.write("VOL08900750712\nINVALID_DNA\n")

        cid = "test-correlation-id"

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id=cid)

        output = f.getvalue()
        log_lines = [line for line in output.split('\n') if line.startswith('JSON_LOG:')]

        self.assertTrue(len(log_lines) >= 3, "Should have at least 3 structured log lines")

        found_start = 0
        found_success = False
        found_error = False

        for line in log_lines:
            log_data = json.loads(line[9:])
            self.assertEqual(log_data['correlation_id'], cid)
            self.assertIn('timestamp', log_data)
            self.assertIn('chain_name', log_data)
            self.assertIn('step', log_data)
            self.assertIn('outcome', log_data)

            if log_data['step'] == 'process_item':
                if log_data['outcome'] == 'start':
                    found_start += 1
                elif log_data['outcome'] == 'success':
                    found_success = True
                    self.assertIn('latency_ms', log_data)
                    self.assertEqual(log_data['idempotency_key'], 'VOL08900750712')
                elif log_data['outcome'] == 'error':
                    found_error = True
                    self.assertEqual(log_data['idempotency_key'], 'INVALID_DNA')

        self.assertEqual(found_start, 2)
        self.assertTrue(found_success)
        self.assertTrue(found_error)

    def test_naming_alignment(self):
        with open(self.input_file, 'w') as f:
            f.write("VOL08900750712\n")

        run_batch(correlation_id="naming-test")

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as jf:
            data = json.load(jf)
            self.assertTrue(len(data) > 0)
            self.assertIn('dna_sequence', data[0])
            self.assertNotIn('dna', data[0])

if __name__ == '__main__':
    unittest.main()
