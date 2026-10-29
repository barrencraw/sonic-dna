import unittest
import os
import json
import shutil
import tempfile
from unittest.mock import patch
from utils.dna_ui import run_batch, PersistenceError, AtomicWriteError, DNAStatus


class TestChainContract(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        self.raw_dir = os.path.join(self.test_dir, 'data', 'raw')
        self.output_dir = os.path.join(self.test_dir, 'data', 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')
        os.makedirs(self.raw_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.rules_dir, exist_ok=True)

        for fname in os.listdir(os.path.join(self.old_cwd, 'rules')):
            if fname.endswith('.json'):
                shutil.copy(
                    os.path.join(self.old_cwd, 'rules', fname),
                    os.path.join(self.rules_dir, fname)
                )

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_happy_path_processing(self):
        """Verify standard batch processing contract execution."""
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(input_file, 'w') as f:
            f.write("VOL08900750712\n")

        run_batch(correlation_id="test-trace-1", actor_id="test_runner")

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        csv_out = os.path.join(self.output_dir, 'toSequence_parsed.csv')
        ledger_file = os.path.join(self.test_dir, 'data', 'processed_ledger.json')

        self.assertTrue(os.path.exists(json_out))
        self.assertTrue(os.path.exists(csv_out))
        self.assertTrue(os.path.exists(ledger_file))

        with open(ledger_file, 'r') as f:
            data = json.load(f)

        ledger = data.get('ledger', data)
        self.assertIn("VOL08900750712", ledger)
        self.assertEqual(ledger["VOL08900750712"]["terminal_outcome"], DNAStatus.SUCCESS.value)

    def test_idempotency_double_invocation(self):
        """Verify double invocation does not duplicate entries or re-process sequences."""
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        seq = "VOL08900750712"
        with open(input_file, 'w') as f:
            f.write(f"{seq}\n")

        run_batch(correlation_id="test-trace-2")

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data1 = json.load(f)
        self.assertEqual(len(data1), 1)

        # Run second time with same input
        with open(input_file, 'w') as f:
            f.write(f"{seq}\n")

        run_batch(correlation_id="test-trace-3")

        with open(json_out, 'r') as f:
            data2 = json.load(f)
        self.assertEqual(len(data2), 1)

    def test_persistence_failure_propagation(self):
        """Verify failure during atomic output commit raises AtomicWriteError."""
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(input_file, 'w') as f:
            f.write("VOL08900750712\n")

        with patch('os.replace', side_effect=OSError("Disk write error")):
            with self.assertRaises(AtomicWriteError):
                run_batch(correlation_id="test-trace-4")


if __name__ == '__main__':
    unittest.main()
