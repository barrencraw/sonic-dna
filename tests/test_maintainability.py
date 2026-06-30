import unittest
import os
import json
import io
from contextlib import redirect_stdout
import inspect
from utils.dna_calculator import DNACalculator
from utils.dna_ui import main as run_batch

class TestMaintainability(unittest.TestCase):
    def test_naming_alignment_dna_sequence(self):
        """
        Enforce canonical name 'dna_sequence' in DNACalculator.parse signature.
        """
        sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', sig.parameters, "DNACalculator.parse must have 'dna_sequence' parameter")

    def test_structured_logging_presence(self):
        """
        Verify that run_batch (dna_ui.main) emits logs with the JSON_LOG: prefix.
        """
        # We need a minimal environment to run run_batch
        project_root = os.getcwd()
        raw_dir = os.path.join(project_root, 'data', 'raw')
        os.makedirs(raw_dir, exist_ok=True)
        input_file = os.path.join(raw_dir, 'toSequence.txt')

        # Clear ledger to ensure processing happens
        ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
        if os.path.exists(ledger_path):
            os.remove(ledger_path)

        with open(input_file, 'w') as f:
            f.write("VOL08900750712\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-guard")

        output = f.getvalue()
        self.assertIn("JSON_LOG:", output, "Output should contain structured logs with 'JSON_LOG:' prefix")

        # Check if the JSON is valid and contains required fields
        found_start = False
        for line in output.splitlines():
            if line.startswith("JSON_LOG:"):
                found_start = True
                log_data = json.loads(line.replace("JSON_LOG: ", ""))
                self.assertIn("correlation_id", log_data)
                self.assertIn("timestamp", log_data)
                self.assertIn("outcome", log_data)
                if log_data["step"] == "start":
                    self.assertEqual(log_data["correlation_id"], "test-guard")

        self.assertTrue(found_start, "Should have found at least one JSON_LOG line")

if __name__ == '__main__':
    unittest.main()
