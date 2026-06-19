import unittest
import os
import json
import shutil
from io import StringIO
import sys
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

        # Backup existing data
        self.backup_folder = os.path.join(self.project_root, 'data_backup_maint')
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

    def test_log_format_and_canonical_naming(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # Capture stdout
        captured_output = StringIO()
        sys.stdout = captured_output
        try:
            run_batch(correlation_id="test-id")
        finally:
            sys.stdout = sys.__stdout__

        output = captured_output.getvalue()

        # Verify JSON_LOG prefix
        log_lines = [line for line in output.split('\n') if line.startswith('JSON_LOG:')]
        self.assertTrue(len(log_lines) > 0, "Should have at least one JSON_LOG entry")

        # Verify log fields
        log_entry = json.loads(log_lines[0].replace('JSON_LOG: ', ''))
        self.assertEqual(log_entry['correlation_id'], "test-id")
        self.assertIn('chain_name', log_entry)
        self.assertIn('step', log_entry)
        self.assertIn('outcome', log_entry)

        # Verify DNAStatus enum values used in logs
        outcomes = [json.loads(line.replace('JSON_LOG: ', ''))['outcome'] for line in log_lines]
        valid_statuses = [s.value for s in DNAStatus]
        for outcome in outcomes:
            self.assertIn(outcome, valid_statuses)

        # Verify canonical naming in JSON output
        with open(self.json_output, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertIn('dna_sequence', data[0])
        self.assertNotIn('dna', data[0])
        self.assertEqual(data[0]['dna_sequence'], dna)

    def test_legacy_migration(self):
        # Create legacy-style output
        legacy_data = [{"dna": "VOL11111111111", "rule": "Volume", "parsed": {}}]
        with open(self.json_output, 'w') as f:
            json.dump(legacy_data, f)

        # Run batch with new DNA
        new_dna = "VOL22222222222"
        with open(self.input_file, 'w') as f:
            f.write(new_dna + "\n")

        run_batch(correlation_id="migration-test")

        # Verify legacy entry was migrated
        with open(self.json_output, 'r') as f:
            data = json.load(f)

        dnas = [entry.get('dna_sequence') for entry in data]
        self.assertIn("VOL11111111111", dnas)
        self.assertIn("VOL22222222222", dnas)
        for entry in data:
            self.assertIn('dna_sequence', entry)
            self.assertNotIn('dna', entry)

if __name__ == '__main__':
    unittest.main()
