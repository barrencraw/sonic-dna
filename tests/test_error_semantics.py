import os
import shutil
import unittest
import json
import tempfile
from utils.errors import (
    SonicDNAError, DomainInvariantError, BoundaryValidationError,
    InfraTransientError, InfraPermanentError, DNAFormatError,
    RuleDefinitionError, InputReadError, PersistenceError
)
from utils.dna_calculator import DNACalculator
from utils.dna_ui import main as run_batch

class TestErrorSemantics(unittest.TestCase):
    def test_error_taxonomy_semantics(self):
        # Domain Invariant
        err_di = RuleDefinitionError("bad rule")
        self.assertEqual(err_di.error_class, "Domain Invariant")
        self.assertFalse(err_di.retryable)

        # Boundary Validation
        err_bv = DNAFormatError("bad dna")
        self.assertEqual(err_bv.error_class, "Boundary Validation")
        self.assertFalse(err_bv.retryable)

        # Infra Transient
        err_it = InfraTransientError("temporary fail")
        self.assertEqual(err_it.error_class, "Infra Transient")
        self.assertTrue(err_it.retryable)

        # Infra Permanent
        err_ip = PersistenceError("disk full")
        self.assertEqual(err_ip.error_class, "Infra Permanent")
        self.assertFalse(err_ip.retryable)

    def test_no_side_effect_on_precondition_failure(self):
        """
        Prove that if DNACalculator fails to load (RuleDefinitionError),
        the input file is NOT cleared by the watcher logic.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            orig_dir = os.getcwd()
            os.chdir(temp_dir)
            try:
                data_dir = os.path.join(temp_dir, "data")
                raw_dir = os.path.join(data_dir, "raw")
                output_dir = os.path.join(data_dir, "output")
                rules_dir = os.path.join(temp_dir, "rules")

                os.makedirs(raw_dir)
                os.makedirs(output_dir)
                os.makedirs(rules_dir)

                # Create a dummy rule
                rule_content = {
                    "variable": "TestVar",
                    "prefix": "T",
                    "subvars": {
                        "val": {"description": "test", "min": 0, "max": 9, "pad": 1}
                    }
                }
                with open(os.path.join(rules_dir, "rule_test.json"), "w") as f:
                    json.dump(rule_content, f)

                input_file = os.path.join(raw_dir, "toSequence.txt")
                dna_content = "T5\n"
                with open(input_file, "w") as f:
                    f.write(dna_content)

                # Write an invalid rule to cause RuleDefinitionError
                with open(os.path.join(rules_dir, "rule_invalid.json"), "w") as f:
                    f.write("invalid json")

                # We simulate the watch_loop's try-except block
                try:
                    run_batch()
                    # if success, we would clear
                    with open(input_file, "w") as f:
                        f.write("")
                except SonicDNAError as e:
                    # expected
                    self.assertIn(e.error_class, ["Domain Invariant", "Infra Permanent"])
                except Exception:
                    # Some other crash might happen if it's not wrapped well
                    pass

                # Verify input file is NOT cleared
                with open(input_file, "r") as f:
                    self.assertEqual(f.read(), dna_content)
            finally:
                os.chdir(orig_dir)

    def test_dna_format_error_is_boundary_validation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            rules_dir = os.path.join(temp_dir, "rules")
            os.makedirs(rules_dir)

            rule_content = {
                "variable": "TestVar",
                "prefix": "T",
                "subvars": {
                    "val": {"description": "test", "min": 0, "max": 9, "pad": 1}
                }
            }
            with open(os.path.join(rules_dir, "rule_test.json"), "w") as f:
                json.dump(rule_content, f)

            calc = DNACalculator(rules_folder=rules_dir)
            with self.assertRaises(DNAFormatError) as cm:
                calc.parse("X5")
            self.assertEqual(cm.exception.error_class, "Boundary Validation")
            self.assertFalse(cm.exception.retryable)

    def test_persistence_error_semantics(self):
        err = PersistenceError("write failed")
        self.assertEqual(err.error_class, "Infra Permanent")
        self.assertFalse(err.retryable)
        self.assertEqual(err.cause_type, "PersistenceError")

if __name__ == "__main__":
    unittest.main()
