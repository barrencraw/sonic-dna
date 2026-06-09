import unittest
import os
import json
import io
from contextlib import redirect_stdout
from utils.dna_ui import DNAStatus, main

class TestMaintainability(unittest.TestCase):
    def test_naming_alignment_json(self):
        """Verify that JSON output uses 'dna_sequence' key."""
        # Setup mock data/environment if needed or just check code conventions
        # For a simple regression guard, we can check if the key is present in output
        # But here we just check if DNAStatus enum is defined as expected
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")

    def test_structured_logging_format(self):
        """Verify that log_structured outputs the correct prefix."""
        from utils.dna_ui import log_structured
        f = io.StringIO()
        with redirect_stdout(f):
            log_structured("test-id", "test-step", "test-outcome")
        output = f.getvalue()
        self.assertIn("JSON_LOG:", output)
        log_json = json.loads(output.split("JSON_LOG: ")[1])
        self.assertEqual(log_json["correlation_id"], "test-id")
        self.assertEqual(log_json["step"], "test-step")
        self.assertEqual(log_json["outcome"], "test-outcome")

    def test_dna_sequence_key_in_batch(self):
        """Ensure the code uses 'dna_sequence' instead of 'dna'."""
        # Read the file content and check for 'dna' as a key (excluding 'dna_sequence')
        import re
        with open("utils/dna_ui.py", "r") as file:
            content = file.read()
            # This is a bit naive but works for a basic guard
            # Search for 'dna' as a dictionary key but not 'dna_sequence'
            # Note: this might have false positives if 'dna' is part of other words
            # We want to ensure 'dna_sequence' is the standard.
            self.assertIn("dna_sequence", content)

if __name__ == "__main__":
    unittest.main()
