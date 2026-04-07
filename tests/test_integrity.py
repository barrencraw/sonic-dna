import unittest
import os
import json
import shutil
import tempfile
from utils.integrity import IntegrityManager

class TestIntegrity(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for test data
        self.test_dir = tempfile.mkdtemp()
        self.state_path = os.path.join(self.test_dir, 'system_integrity.json')

    def tearDown(self):
        # Remove the temporary directory after tests
        shutil.rmtree(self.test_dir)

    def test_initial_integrity(self):
        mgr = IntegrityManager(state_path=self.state_path)
        self.assertEqual(mgr.integrity, 100)

    def test_normal_wear(self):
        mgr = IntegrityManager(state_path=self.state_path)
        # Non-TEX or high-scarcity TEX
        parsed_dna = {'rule': 'Volume', 'values': {'amp': 5000}}
        mgr.apply_wear(parsed_dna)
        self.assertEqual(mgr.integrity, 98)

    def test_heavy_wear(self):
        mgr = IntegrityManager(state_path=self.state_path)
        # TEX with scarcity > 8000
        parsed_dna = {'rule': 'Texture Complexity', 'values': {'scarcity': 9000}}
        mgr.apply_wear(parsed_dna)
        self.assertEqual(mgr.integrity, 95)

    def test_maintenance_restoration(self):
        mgr = IntegrityManager(state_path=self.state_path)
        mgr.integrity = 50
        # TEX with scarcity < 1000
        parsed_dna = {'rule': 'Texture Complexity', 'values': {'scarcity': 500}}
        mgr.apply_wear(parsed_dna)
        self.assertEqual(mgr.integrity, 60)

    def test_integrity_clamping(self):
        mgr = IntegrityManager(state_path=self.state_path)
        # Test upper clamp
        parsed_dna = {'rule': 'Texture Complexity', 'values': {'scarcity': 500}}
        mgr.apply_wear(parsed_dna)
        self.assertEqual(mgr.integrity, 100)

        # Test lower clamp
        mgr.integrity = 1
        parsed_dna = {'rule': 'Volume', 'values': {'amp': 5000}}
        mgr.apply_wear(parsed_dna)
        self.assertEqual(mgr.integrity, 0)

    def test_can_process_refusal(self):
        mgr = IntegrityManager(state_path=self.state_path)
        mgr.integrity = 0

        # Non-maintenance should be refused
        vol_dna = {'rule': 'Volume', 'values': {'amp': 5000}}
        self.assertFalse(mgr.can_process(vol_dna))

        # Maintenance should be allowed
        maint_dna = {'rule': 'Texture Complexity', 'values': {'scarcity': 500}}
        self.assertTrue(mgr.can_process(maint_dna))

    def test_persistence(self):
        mgr = IntegrityManager(state_path=self.state_path)
        mgr.integrity = 80
        mgr._save_state()

        mgr2 = IntegrityManager(state_path=self.state_path)
        self.assertEqual(mgr2.integrity, 80)

if __name__ == '__main__':
    unittest.main()
