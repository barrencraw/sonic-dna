import os
import json

class IntegrityManager:
    def __init__(self, state_path=None):
        self.state_path = state_path
        self.integrity = 100
        if state_path and os.path.exists(state_path):
            try:
                with open(state_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.integrity = data.get('integrity', 100)
            except Exception:
                self.integrity = 100

    def is_maintenance_dna(self, dna_result):
        if dna_result.get('rule') == 'Texture Complexity':
            scarcity = dna_result.get('values', {}).get('scarcity', 0)
            return scarcity > 8000
        return False

    def is_refusing(self, dna_result):
        if self.integrity <= 0:
            # Only maintenance DNA can bypass refusal
            if not self.is_maintenance_dna(dna_result):
                return True
        return False

    def calculate_wear(self, dna_result):
        if dna_result.get('rule') == 'Texture Complexity':
            scarcity = dna_result.get('values', {}).get('scarcity', 0)
            if scarcity < 2000:
                return -5
            elif scarcity > 8000:
                return 10  # Restoration
        return -2

    def apply_wear(self, dna_result):
        wear = self.calculate_wear(dna_result)
        self.integrity = max(0, min(100, self.integrity + wear))
        return wear

    def to_dict(self):
        return {'integrity': self.integrity}
