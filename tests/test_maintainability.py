import unittest
import os
import json
import subprocess
import sys

class TestMaintainability(unittest.TestCase):
    def test_naming_alignment(self):
        """Ensure 'dna_sequence' is used instead of 'dna' or 'dna_str' in core files."""
        core_files = ['utils/dna_calculator.py', 'utils/dna_ui.py']
        forbidden = ['dna_str'] # 'dna' is too common (e.g. within 'dna_sequence'), but we can check JSON keys

        for filepath in core_files:
            with open(filepath, 'r') as f:
                content = f.read()
                for word in forbidden:
                    self.assertNotIn(word, content, f"Forbidden word '{word}' found in {filepath}")

    def test_json_log_format(self):
        """Ensure logs follow the structured format with 'JSON_LOG:' prefix."""
        # We can inspect utils/dna_ui.py to see if log_structured uses the prefix
        with open('utils/dna_ui.py', 'r') as f:
            content = f.read()
            self.assertIn('JSON_LOG: ', content)
            self.assertIn('"correlation_id": correlation_id', content)
            self.assertIn('"chain_name": chain_name', content)
            self.assertIn('"step": step', content)
            self.assertIn('"outcome": outcome', content)

    def test_dna_sequence_key_in_output(self):
        """Verify that 'dna_sequence' is used as a key in the JSON output."""
        project_root = os.getcwd()
        data_dir = os.path.join(project_root, 'data')
        raw_dir = os.path.join(data_dir, 'raw')
        output_dir = os.path.join(data_dir, 'output')
        os.makedirs(raw_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)

        input_file = os.path.join(raw_dir, 'toSequence.txt')
        with open(input_file, 'w') as f:
            f.write("VOL08900750712\n")

        # Run batch via subprocess to capture output if needed, or just call main
        from utils.dna_ui import main as run_batch
        run_batch(correlation_id="test-ref", actor_id="maintainability-test")

        json_out = os.path.join(output_dir, 'toSequence_parsed.json')
        self.assertTrue(os.path.exists(json_out))

        with open(json_out, 'r') as f:
            data = json.load(f)
            if data:
                self.assertIn('dna_sequence', data[0])
                self.assertNotIn('dna', data[0])

if __name__ == '__main__':
    unittest.main()
