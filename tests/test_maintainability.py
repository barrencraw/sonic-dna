import unittest
import os
import json
import io
from contextlib import redirect_stdout
from utils.dna_ui import DNAStatus, main as run_batch

class TestMaintainability(unittest.TestCase):
    def test_dna_status_enum(self):
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")

    def test_dna_sequence_key_in_output(self):
        project_root = os.getcwd()
        raw_folder = os.path.join(project_root, 'data', 'raw')
        output_folder = os.path.join(project_root, 'data', 'output')
        os.makedirs(raw_folder, exist_ok=True)

        input_file = os.path.join(raw_folder, 'toSequence.txt')
        dna = "VOL08900750712"
        with open(input_file, 'w') as f:
            f.write(dna + "\n")

        # Clean ledger to ensure processing
        ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
        if os.path.exists(ledger_path):
            os.remove(ledger_path)

        run_batch(correlation_id="test-cid")

        json_output = os.path.join(output_folder, 'toSequence_parsed.json')
        with open(json_output, 'r') as f:
            data = json.load(f)

        self.assertTrue(len(data) > 0)
        self.assertIn('dna_sequence', data[0])
        self.assertNotIn('dna', data[0])

    def test_structured_logging_format(self):
        project_root = os.getcwd()
        raw_folder = os.path.join(project_root, 'data', 'raw')
        os.makedirs(raw_folder, exist_ok=True)
        input_file = os.path.join(raw_folder, 'toSequence.txt')
        with open(input_file, 'w') as f:
            f.write("VOL08900750712\n")

        # Clean ledger
        ledger_path = os.path.join(project_root, 'data', 'processed_ledger.json')
        if os.path.exists(ledger_path):
            os.remove(ledger_path)

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-correlation-id")

        output = f.getvalue()
        lines = [l for l in output.splitlines() if l.startswith("JSON_LOG:")]
        self.assertTrue(len(lines) > 0)

        for line in lines:
            json_str = line.replace("JSON_LOG: ", "")
            log_data = json.loads(json_str)
            self.assertEqual(log_data['correlation_id'], "test-correlation-id")
            self.assertIn('chain_name', log_data)
            self.assertIn('step', log_data)
            self.assertIn('outcome', log_data)

if __name__ == '__main__':
    unittest.main()
