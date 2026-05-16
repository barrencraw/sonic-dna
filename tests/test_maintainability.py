import os
import json
import io
import contextlib
import unittest
import inspect
from utils.dna_calculator import DNACalculator
from utils.dna_ui import main as run_batch, TerminalOutcome

class TestMaintainability(unittest.TestCase):
    def test_canonical_naming_alignment(self):
        """Verify that DNACalculator.parse uses 'dna_sequence' as parameter name."""
        sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', sig.parameters)

    def test_terminal_outcome_enum_usage(self):
        """Verify that ledger uses TerminalOutcome values."""
        project_root = os.getcwd()
        data_folder = os.path.join(project_root, 'data')
        raw_folder = os.path.join(data_folder, 'raw')
        ledger_path = os.path.join(data_folder, 'processed_ledger.json')

        os.makedirs(raw_folder, exist_ok=True)
        input_file = os.path.join(raw_folder, 'toSequence.txt')

        dna = "VOL08900750712"
        with open(input_file, 'w') as f:
            f.write(dna + "\n")

        # Run batch
        run_batch()

        with open(ledger_path, 'r') as f:
            ledger = json.load(f)

        self.assertIn(dna, ledger)
        # It should match one of the Enum values
        valid_outcomes = [e.value for e in TerminalOutcome]
        self.assertIn(ledger[dna]['terminal_outcome'], valid_outcomes)

    def test_structured_logging_fields(self):
        """Verify that structured logs contain required fields."""
        # Ensure there is something to process so batch_complete is reached after work
        project_root = os.getcwd()
        raw_folder = os.path.join(project_root, 'data', 'raw')
        os.makedirs(raw_folder, exist_ok=True)
        input_file = os.path.join(raw_folder, 'toSequence.txt')
        with open(input_file, 'w') as f:
            f.write("VOL00000000001\n")

        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            run_batch()

        output = f.getvalue().strip()
        lines = output.split('\n')

        required_fields = {
            "timestamp", "correlation_id", "actor_id",
            "chain_name", "step", "outcome", "latency_ms"
        }

        found_batch_complete = False
        for line in lines:
            try:
                log_entry = json.loads(line)
                if log_entry.get("step") == "batch_complete":
                    found_batch_complete = True
                    for field in required_fields:
                        self.assertIn(field, log_entry, f"Missing field {field} in log")
            except json.JSONDecodeError:
                continue

        self.assertTrue(found_batch_complete, "Should have found 'batch_complete' log entry")

if __name__ == '__main__':
    unittest.main()
