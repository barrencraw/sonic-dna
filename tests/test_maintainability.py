import unittest
import json
import os
import subprocess
import sys
from utils.dna_ui import DNAStatus

class TestMaintainability(unittest.TestCase):
    def test_log_structured_format(self):
        """Verify that log_structured produces the expected JSON format with mandatory fields."""
        from utils.dna_ui import log_structured
        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with redirect_stdout(f):
            log_structured(
                correlation_id="test-id",
                chain_name="test-chain",
                step="test-step",
                outcome=DNAStatus.SUCCESS.value,
                idempotency_key="test-dna"
            )

        output = f.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "))
        log_json = json.loads(output[len("JSON_LOG: "):])

        mandatory_fields = ["timestamp", "correlation_id", "chain_name", "step", "outcome", "actor_id", "idempotency_key"]
        for field in mandatory_fields:
            self.assertIn(field, log_json)

        self.assertEqual(log_json["correlation_id"], "test-id")
        self.assertEqual(log_json["outcome"], "success")

    def test_dna_sequence_naming_alignment(self):
        """Verify that 'dna_sequence' is used in output JSON keys."""
        # This is a bit of an integration test
        from utils.dna_ui import main as run_batch
        raw_dir = "data/raw"
        os.makedirs(raw_dir, exist_ok=True)
        to_sequence_file = os.path.join(raw_dir, "toSequence.txt")
        with open(to_sequence_file, "w") as f:
            f.write("VOL12345678901\n") # Assume VOL is a valid prefix from exploring rules

        # Run batch directly to avoid missing dependencies in main.py
        try:
            run_batch(correlation_id="test-alignment")

            output_json = "data/output/toSequence_parsed.json"
            self.assertTrue(os.path.exists(output_json), "Output JSON file should be created")
            with open(output_json, "r") as f:
                data = json.load(f)
                self.assertTrue(len(data) > 0, "Output JSON should not be empty")
                self.assertIn("dna_sequence", data[0])
                self.assertNotIn("dna", data[0])
        finally:
            # Cleanup if needed or leave for inspection
            pass

if __name__ == "__main__":
    unittest.main()
