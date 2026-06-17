import os
import json
import shutil
import unittest
import subprocess
import csv

class TestMaintainability(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')
        self.csv_output = os.path.join(self.output_folder, 'toSequence_parsed.csv')

        # Clean state
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

    def test_canonical_naming_in_outputs(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # Run via subprocess to capture stdout for log testing too
        result = subprocess.run(
            ["python3", "main.py", "--once"],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": "."}
        )
        self.assertEqual(result.returncode, 0)

        # 1. Check JSON keys
        with open(self.json_output, 'r') as f:
            data = json.load(f)
        self.assertTrue(len(data) > 0)
        self.assertIn('dna_sequence', data[0])
        self.assertNotIn('dna', data[0])

        # 2. Check CSV headers
        with open(self.csv_output, 'r') as f:
            reader = csv.DictReader(f)
            self.assertIn('dna_sequence', reader.fieldnames)
            self.assertNotIn('dna', reader.fieldnames)

    def test_structured_logging_format(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        result = subprocess.run(
            ["python3", "main.py", "--once"],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": "."}
        )

        found_log = False
        for line in result.stdout.splitlines():
            if line.startswith("JSON_LOG: "):
                found_log = True
                log_json = json.loads(line[len("JSON_LOG: "):])
                # Check required fields
                required_fields = ["timestamp", "correlation_id", "chain_name", "step", "outcome"]
                for field in required_fields:
                    self.assertIn(field, log_json)

                # Check for UUID format in correlation_id (simple check)
                self.assertTrue(len(log_json["correlation_id"]) > 30)

        self.assertTrue(found_log, "No JSON_LOG: found in stdout")

if __name__ == '__main__':
    unittest.main()
