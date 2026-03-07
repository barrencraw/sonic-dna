import unittest
import os
import json
import io
import contextlib
from utils.dna_ui import main as run_batch, DNAProcessingOutcome

class TestMaintainability(unittest.TestCase):
    def test_observability_log_format(self):
        """Verify that observability logs follow the [OBSERVABILITY] JSON format."""
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            # Run with a dummy correlation_id and no input strings to trigger 'empty' or 'terminal'
            run_batch(correlation_id="test-cid")

        log_lines = [line for line in output.getvalue().split('\n') if "[OBSERVABILITY]" in line or (line.startswith('{') and '"tag": "OBSERVABILITY"' in line)]

        self.assertGreater(len(log_lines), 0, "No observability logs found")

        for line in log_lines:
            try:
                log_data = json.loads(line)
                self.assertEqual(log_data["tag"], "OBSERVABILITY")
                self.assertIn("correlation_id", log_data)
                self.assertIn("actor_id", log_data)
                self.assertIn("chain_name", log_data)
                self.assertIn("step", log_data)
                self.assertIn("outcome", log_data)
                self.assertEqual(log_data["correlation_id"], "test-cid")
            except json.JSONDecodeError:
                self.fail(f"Log line is not valid JSON: {line}")

    def test_naming_alignment_presence(self):
        """Regression guard for naming: check if canonical names are present in source files."""
        utils_dir = os.path.join(os.getcwd(), 'utils')
        dna_ui_path = os.path.join(utils_dir, 'dna_ui.py')
        dna_calc_path = os.path.join(utils_dir, 'dna_calculator.py')

        with open(dna_ui_path, 'r') as f:
            content = f.read()
            self.assertIn('raw_dna', content)
            self.assertIn('processing_result', content)

        with open(dna_calc_path, 'r') as f:
            content = f.read()
            self.assertIn('raw_dna', content)
            self.assertIn('processing_result', content)

if __name__ == '__main__':
    unittest.main()
