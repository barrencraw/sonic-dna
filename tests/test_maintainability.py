import unittest
import os
import json
import csv
import shutil
import io
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch

class TestMaintainability(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')
        self.csv_output = os.path.join(self.output_folder, 'toSequence_parsed.csv')

        # Cleanup and setup
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

    def test_naming_alignment_in_outputs(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch(correlation_id="test-id")

        # Verify JSON
        with open(self.json_output, 'r') as f:
            data = json.load(f)
            self.assertIn('dna_sequence', data[0])
            self.assertEqual(data[0]['dna_sequence'], dna)

        # Verify CSV
        with open(self.csv_output, 'r') as f:
            reader = csv.DictReader(f)
            self.assertIn('dna_sequence', reader.fieldnames)
            row = next(reader)
            self.assertEqual(row['dna_sequence'], dna)

    def test_structured_logging_format(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-id-123")

        output = f.getvalue()
        log_lines = [line for line in output.split('\n') if line.startswith('JSON_LOG:')]

        self.assertTrue(len(log_lines) >= 2) # At least parse and complete

        for line in log_lines:
            json_str = line.replace('JSON_LOG: ', '')
            log_data = json.loads(json_str)
            self.assertEqual(log_data['correlation_id'], "test-id-123")
            self.assertEqual(log_data['chain_name'], "dna_batch_processing")
            self.assertIn('step', log_data)
            self.assertIn('outcome', log_data)
            self.assertIn('timestamp', log_data)

if __name__ == '__main__':
    unittest.main()
