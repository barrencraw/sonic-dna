import os
import json

class IntegrityManager:
    def __init__(self, state_path):
        self.state_path = state_path
        self.integrity = 100
        self.load_state()

    def load_state(self):
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.integrity = data.get('integrity', 100)
            except Exception:
                self.integrity = 100

    def calculate_new_integrity(self, current_integrity, result):
        new_integrity = current_integrity
        if result.get('rule') == 'Texture Complexity':
            scarcity = result.get('values', {}).get('scarcity', 0)
            if scarcity < 2000:
                new_integrity -= 5
            elif scarcity > 8000:
                new_integrity += 10
            else:
                new_integrity -= 2
        else:
            new_integrity -= 2

        # Clamp
        if new_integrity < 0:
            new_integrity = 0
        if new_integrity > 100:
            new_integrity = 100

        return new_integrity

    def is_maintenance(self, result):
        if result.get('rule') == 'Texture Complexity':
            scarcity = result.get('values', {}).get('scarcity', 0)
            if scarcity > 8000:
                return True
        return False

    def is_refusal(self, current_integrity, result):
        if current_integrity <= 0 and not self.is_maintenance(result):
            return True
        return False
