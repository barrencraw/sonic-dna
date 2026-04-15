import unittest
import os
import json
import shutil
import tempfile
from io import StringIO
from unittest.mock import patch
from utils.dna_ui import main as run_batch, Outcome

class TestObservability(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.raw_folder = os.path.join(self.test_dir, 'data', 'raw')
        self.rules_folder = os.path.join(self.test_dir, 'rules')
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.rules_folder, exist_ok=True)

        # Copy rules to test dir
        original_rules = os.path.join(os.getcwd(), 'rules')
        for item in os.listdir(original_rules):
            s = os.path.join(original_rules, item)
            d = os.path.join(self.rules_folder, item)
            if os.path.isfile(s):
                shutil.copy2(s, d)

        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_observability_logs(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        with patch('sys.stdout', new=StringIO()) as fake_out:
            run_batch(data_dir=self.test_dir)
            output = fake_out.getvalue()

        # Check for structured logs in output
        log_lines = [line for line in output.split('\n') if line.startswith('[OBSERVABILITY]')]
        self.assertTrue(len(log_lines) >= 3) # start, parse, complete (and maybe persist)

        found_start = False
        found_parse_success = False
        found_complete = False

        for line in log_lines:
            json_str = line[len('[OBSERVABILITY] '):]
            log_data = json.loads(json_str)
            self.assertEqual(log_data['chain_name'], 'dna_batch_chain')
            self.assertIn('correlation_id', log_data)
            self.assertIn('timestamp', log_data)

            if log_data['step'] == 'start':
                found_start = True
                self.assertEqual(log_data['outcome'], Outcome.START.value)
            if log_data['step'] == 'parse' and log_data['idempotency_key'] == dna:
                found_parse_success = True
                self.assertEqual(log_data['outcome'], Outcome.SUCCESS.value)
            if log_data['step'] == 'complete':
                found_complete = True
                self.assertEqual(log_data['outcome'], Outcome.END.value)

        self.assertTrue(found_start)
        self.assertTrue(found_parse_success)
        self.assertTrue(found_complete)

if __name__ == '__main__':
    unittest.main()
