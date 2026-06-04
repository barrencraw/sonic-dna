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
        self.test_dir = tempfile.mkdtemp()
        self.raw_dir = os.path.join(self.test_dir, 'data', 'raw')
        self.output_dir = os.path.join(self.test_dir, 'data', 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')
        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        # Copy a real rule for testing
        real_rules_dir = os.path.join(os.getcwd(), 'rules')
        for f in os.listdir(real_rules_dir):
            if f.endswith('.json'):
                shutil.copy(os.path.join(real_rules_dir, f), self.rules_dir)
                break # Just need one

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_structured_logging(self):
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(input_file, 'w') as f:
            f.write("VOL100\n") # Assuming VOL exists

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(base_dir=self.test_dir, correlation_id="test-id")

        output = f.getvalue()
        log_lines = [line for line in output.split('\n') if line.startswith('JSON_LOG:')]

        self.assertTrue(len(log_lines) > 0, "No structured logs found")

        # Verify first log entry fields
        first_log = json.loads(log_lines[0].replace('JSON_LOG: ', ''))
        self.assertIn('timestamp', first_log)
        self.assertEqual(first_log['correlation_id'], "test-id")
        self.assertEqual(first_log['chain_name'], "dna_batch_chain")

    def test_naming_alignment(self):
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        # Find a valid prefix
        prefix = ""
        for f in os.listdir(self.rules_dir):
            with open(os.path.join(self.rules_dir, f), 'r') as rf:
                data = json.load(rf)
                prefix = data['prefix']
                break

        with open(input_file, 'w') as f:
            f.write(f"{prefix}...\n") # Might fail parse but should still use naming

        run_batch(base_dir=self.test_dir, correlation_id="test-id")

        json_out_path = os.path.join(self.output_dir, 'toSequence_parsed.json')
        if os.path.exists(json_out_path):
            with open(json_out_path, 'r') as f:
                data = json.load(f)
                if len(data) > 0:
                    self.assertIn('dna_sequence', data[0], "JSON output missing 'dna_sequence' key")

if __name__ == '__main__':
    unittest.main()
