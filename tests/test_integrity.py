import os
import json
import shutil
import unittest
from utils.integrity import IntegrityManager

class TestIntegrity(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.test_data = os.path.join(self.project_root, 'test_integrity_data')
        os.makedirs(self.test_data, exist_ok=True)
        self.integrity_path = os.path.join(self.test_data, 'system_integrity.json')
        self.messages_path = os.path.join(self.test_data, 'system_messages.json')

        # Create mock messages
        self.messages = {
            "integrity": {
                "consequence_applied": "Change: {change}, Integrity: {integrity}",
                "refusal_reason": "Refused.",
                "next_action_hint": "Hint."
            }
        }
        with open(self.messages_path, 'w', encoding='utf-8') as f:
            json.dump(self.messages, f)

    def tearDown(self):
        shutil.rmtree(self.test_data)

    def test_wear_and_maintenance(self):
        mgr = IntegrityManager(self.integrity_path, self.messages_path)
        self.assertEqual(mgr.integrity, 100)

        # Normal wear (-2)
        msg = mgr.apply_wear("VOL08900750712")
        self.assertEqual(mgr.integrity, 98)
        self.assertIn("Change: -2", msg)
        self.assertIn("Integrity: 98", msg)

        # Heavy load (-5)
        # TEX + scarcity(5 digits) > 8000
        msg = mgr.apply_wear("TEX09000Z000000000Z")
        self.assertEqual(mgr.integrity, 93)
        self.assertIn("Change: -5", msg)

        # Maintenance (+10)
        # TEX + scarcity(5 digits) < 1000
        msg = mgr.apply_wear("TEX00500Z000000000Z")
        self.assertEqual(mgr.integrity, 100) # Clamped at 100
        self.assertIn("Change: 7", msg) # 93 -> 100 is +7

    def test_refusal_at_zero(self):
        mgr = IntegrityManager(self.integrity_path, self.messages_path)
        mgr.integrity = 0

        # Normal DNA refused
        self.assertFalse(mgr.can_process("VOL08900750712"))

        # Heavy load DNA refused
        self.assertFalse(mgr.can_process("TEX09000Z000000000Z"))

        # Maintenance DNA allowed
        self.assertTrue(mgr.can_process("TEX00500Z000000000Z"))

        self.assertIn("Refused. Hint.", mgr.get_refusal_message())

    def test_persistence(self):
        mgr = IntegrityManager(self.integrity_path, self.messages_path)
        mgr.integrity = 50
        mgr.save()

        mgr2 = IntegrityManager(self.integrity_path, self.messages_path)
        self.assertEqual(mgr2.integrity, 50)

if __name__ == '__main__':
    unittest.main()
