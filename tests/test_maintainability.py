import unittest
import io
import json
import inspect
from unittest.mock import patch
from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    RuleLoadError,
    InputReadError,
    PersistenceError,
    LedgerSaveError,
    AtomicWriteError,
    log_structured,
    read_input_file
)

class TestMaintainability(unittest.TestCase):
    def test_dna_status_enum(self):
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_exception_taxonomy(self):
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))

    def test_naming_alignment_docstrings(self):
        doc = read_input_file.__doc__ or ""
        self.assertIn("DNA sequence", doc)

    def test_structured_log_fields(self):
        with patch('sys.stdout', new=io.StringIO()) as fake_out:
            log_structured(
                correlation_id="corr-123",
                actor_id="test_actor",
                chain_name="test_chain",
                step="test_step",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=12.34,
                idempotency_key="key-456",
                outcome_detail="detail_msg"
            )
            output = fake_out.getvalue().strip()

        self.assertTrue(output.startswith("JSON_LOG:"))
        json_str = output[len("JSON_LOG:"):]
        log_entry = json.loads(json_str)

        required_keys = {
            "timestamp",
            "correlation_id",
            "actor_id",
            "chain_name",
            "step",
            "outcome",
            "latency_ms",
            "idempotency_key",
            "outcome_detail"
        }
        self.assertTrue(required_keys.issubset(set(log_entry.keys())))
        self.assertEqual(log_entry["correlation_id"], "corr-123")
        self.assertEqual(log_entry["actor_id"], "test_actor")
        self.assertEqual(log_entry["chain_name"], "test_chain")
        self.assertEqual(log_entry["step"], "test_step")
        self.assertEqual(log_entry["outcome"], "success")
        self.assertEqual(log_entry["latency_ms"], 12.34)
        self.assertEqual(log_entry["idempotency_key"], "key-456")

if __name__ == '__main__':
    unittest.main()
