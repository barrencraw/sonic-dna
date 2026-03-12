import unittest
import os
import json
import shutil
import tempfile
from utils.dna_ui import main as run_batch
from utils.integrity_manager import IntegrityManager

class TestSystemIntegrity(unittest.TestCase):
    def setUp(self):
        # Create a temporary project structure
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Setup folders
        os.makedirs("rules")
        os.makedirs("data/raw")
        os.makedirs("data/output")

        # Copy rules (simplified for test or copy real ones)
        # We'll create a minimal TEX rule
        self.tex_rule = {
            "variable": "Texture Complexity",
            "prefix": "TEX",
            "subvars": {
                "scarcity": {"min": 0, "max": 10000, "pad": 5, "description": "S"},
                "granularity": {"class": "Z-A", "description": "G"},
                "layering": {"min": 0, "max": 1000, "pad": 4, "description": "L"},
                "variation": {"min": 0, "max": 10000, "pad": 5, "description": "V"},
                "spectral": {"class": "Z-A", "description": "Spec"}
            }
        }
        with open("rules/rules_Texture_Complexity.json", "w") as f:
            json.dump(self.tex_rule, f)

        # Create system messages
        self.messages = {
            "consequence_applied": "Drain.",
            "refusal_reason": "Low Integrity.",
            "next_action_hint": "Maintenance."
        }
        with open("data/system_messages.json", "w") as f:
            json.dump(self.messages, f)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def write_dna(self, dnas):
        with open("data/raw/toSequence.txt", "w") as f:
            for dna in dnas:
                f.write(dna + "\n")

    def get_integrity(self):
        with open("data/system_integrity.json", "r") as f:
            return json.load(f)["integrity"]

    def test_integrity_drain_and_restore(self):
        # Initial integrity 100
        # High layering DNA (drain 10)
        # TEX scarcity(5) granularity(1) layering(4) variation(5) spectral(1)
        # TEX 00000 Z 0600 00000 Z
        drain_dna = "TEX00000Z060000000Z"
        self.write_dna([drain_dna])
        run_batch()
        self.assertEqual(self.get_integrity(), 90)

        # Maintenance DNA (restore 5)
        # TEX 09500 Z 0000 00000 Z
        restore_dna = "TEX09500Z000000000Z"
        self.write_dna([restore_dna])
        run_batch()
        self.assertEqual(self.get_integrity(), 95)

    def test_refusal_at_zero(self):
        # Force integrity to 0
        with open("data/system_integrity.json", "w") as f:
            json.dump({"integrity": 0}, f)

        # Normal DNA (should be refused)
        normal_dna = "TEX00000Z000000000Z"
        self.write_dna([normal_dna])
        run_batch()

        with open("data/output/toSequence_parsed.json", "r") as f:
            results = json.load(f)
            self.assertEqual(results[0]["outcome"], "REFUSAL")
            self.assertEqual(results[0]["refusal_reason"], "Low Integrity.")

        # Maintenance DNA (should still work at 0)
        restore_dna = "TEX09500Z000000000Z"
        self.write_dna([restore_dna])
        run_batch()

        with open("data/output/toSequence_parsed.json", "r") as f:
            results = json.load(f)
            # Find the restore_dna entry
            restore_entry = next(e for e in results if e["dna"] == restore_dna)
            self.assertEqual(restore_entry["outcome"], "SUCCESS")
            self.assertEqual(self.get_integrity(), 5)

    def test_idempotency_integrity(self):
        # Processing same DNA twice should only drain once
        drain_dna = "TEX00000Z060000000Z"
        self.write_dna([drain_dna])
        run_batch()
        self.assertEqual(self.get_integrity(), 90)

        # Run again with same DNA
        run_batch()
        self.assertEqual(self.get_integrity(), 90) # Should not drain again

if __name__ == "__main__":
    unittest.main()
