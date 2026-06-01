import unittest
import os
import json
import io
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch, DNAStatus

class TestMaintainability(unittest.TestCase):
    def test_naming_alignment(self):
        """Ensure 'dna_sequence' is used in JSON output instead of 'dna'."""
        project_root = os.getcwd()
        raw_folder = os.path.join(project_root, 'data', 'raw')
        output_folder = os.path.join(project_root, 'data', 'output')
        os.makedirs(raw_folder, exist_ok=True)

        input_file = os.path.join(raw_folder, 'toSequence.txt')
        with open(input_file, 'w') as f:
            f.write("VOL08900750712\n")

        run_batch(correlation_id="test-cid")

        json_out = os.path.join(output_folder, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)
            self.assertIn('dna_sequence', data[0])
            self.assertNotIn('dna', data[0])

    def test_structured_logging_format(self):
        """Ensure logs are prefixed with JSON_LOG: and contain required fields."""
        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-cid-123")

        output = f.getvalue()
        found_log = False
        for line in output.splitlines():
            if line.startswith("JSON_LOG: "):
                found_log = True
                log_data = json.loads(line[10:])
                self.assertEqual(log_data['correlation_id'], "test-cid-123")
                self.assertIn('timestamp', log_data)
                self.assertIn('chain_name', log_data)
                self.assertIn('step', log_data)
                self.assertIn('outcome', log_data)
        self.assertTrue(found_log, "No structured log found in output")

    def test_dna_status_enum_usage(self):
        """Ensure DNAStatus enum values are used correctly."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.PARSE_ERROR.value, "error")

if __name__ == '__main__':
    unittest.main()
