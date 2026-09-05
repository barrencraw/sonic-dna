import os
import json
import io
import shutil
import unittest
from unittest.mock import patch
from utils.dna_ui import (
    main as run_batch,
    DNAStatus,
    log_structured
)

class TestMaintainability(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        self.backup_folder = os.path.join(self.project_root, 'data_backup')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_dnastatus_lowercase_values(self):
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_structured_log_schema(self):
        buf = io.StringIO()
        with patch('sys.stdout', buf):
            log_structured(
                "test_step",
                correlation_id="test-uuid",
                actor_id="test_actor",
                idempotency_key="VOL08900750712",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=42,
                outcome_detail="test detail"
            )

        output = buf.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG:"))

        json_str = output[len("JSON_LOG:"):]
        log_data = json.loads(json_str)

        required_keys = [
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        ]
        for key in required_keys:
            self.assertIn(key, log_data)

        self.assertEqual(log_data["correlation_id"], "test-uuid")
        self.assertEqual(log_data["actor_id"], "test_actor")
        self.assertEqual(log_data["chain_name"], "dna_batch_parsing")
        self.assertEqual(log_data["step"], "test_step")
        self.assertEqual(log_data["outcome"], "success")

    def test_dual_output_keys_backwards_compatibility(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        self.assertEqual(len(data), 1)
        entry = data[0]
        self.assertIn("dna", entry)
        self.assertIn("dna_sequence", entry)
        self.assertEqual(entry["dna"], dna)
        self.assertEqual(entry["dna_sequence"], dna)

if __name__ == '__main__':
    unittest.main()
