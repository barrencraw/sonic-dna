import unittest
import os
import json
import shutil
import io
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch, DNAStatus

class TestMaintainability(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')
        self.csv_output = os.path.join(self.output_folder, 'toSequence_parsed.csv')

        # Backup existing data
        self.backup_folder = os.path.join(self.project_root, 'data_backup_maintainability')
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

    def test_naming_alignment_and_logs(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-correlation-id", actor_id="test-actor")

        output = f.getvalue()

        # 1. Check for structured logs
        log_lines = [line for line in output.split('\n') if line.startswith('JSON_LOG:')]
        self.assertTrue(len(log_lines) > 0, "No structured logs found")

        found_item_processed = False
        for line in log_lines:
            log_data = json.loads(line.replace('JSON_LOG: ', ''))
            self.assertIn('correlation_id', log_data)
            self.assertIn('chain_name', log_data)
            self.assertIn('timestamp', log_data)

            if log_data.get('step') == 'process_item':
                found_item_processed = True
                self.assertEqual(log_data['correlation_id'], "test-correlation-id")
                self.assertEqual(log_data['actor_id'], "test-actor")
                self.assertEqual(log_data['outcome'], DNAStatus.SUCCESS.value)
                self.assertIn('latency_ms', log_data)

        self.assertTrue(found_item_processed, "Did not find 'process_item' step in logs")

        # 2. Check naming alignment in output files
        with open(self.json_output, 'r') as jf:
            parsed_json = json.load(jf)
            self.assertEqual(parsed_json[0]['dna_sequence'], dna)
            self.assertNotIn('dna', parsed_json[0])

        with open(self.csv_output, 'r') as cf:
            content = cf.read()
            self.assertIn('dna_sequence', content)
            self.assertNotIn(',dna,', content)

    def test_dna_status_enum_usage(self):
        # Verify DNAStatus values are as expected
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.PARSE_ERROR.value, "parse_error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")

if __name__ == '__main__':
    unittest.main()
