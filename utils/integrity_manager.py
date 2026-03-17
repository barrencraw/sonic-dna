import json
import os

class IntegrityManager:
    DEFAULT_INTEGRITY = 100

    def __init__(self, integrity_path):
        self.integrity_path = integrity_path
        self.integrity = self.load_state()

    def load_state(self):
        if os.path.exists(self.integrity_path):
            try:
                with open(self.integrity_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('integrity', self.DEFAULT_INTEGRITY)
            except Exception:
                return self.DEFAULT_INTEGRITY
        return self.DEFAULT_INTEGRITY

    def calculate_wear(self, result):
        """
        Determines integrity change based on the parsed DNA result.
        - TEX with Scarcity < 2000: -5
        - TEX with Scarcity > 8000: +10 (Maintenance)
        - Others: -2
        """
        if result.get('rule') == 'Texture Complexity':
            scarcity = result.get('values', {}).get('scarcity', 5000)
            if scarcity < 2000:
                return -5
            elif scarcity > 8000:
                return 10
        return -2

    def apply_wear(self, change):
        self.integrity = max(0, min(100, self.integrity + change))
        return self.integrity

    def is_refusal(self, result):
        """
        Refuse processing if integrity is 0, unless it's a maintenance DNA.
        """
        if self.integrity > 0:
            return False

        # If integrity is 0, only allow maintenance DNA
        if result.get('rule') == 'Texture Complexity':
            scarcity = result.get('values', {}).get('scarcity', 5000)
            if scarcity > 8000:
                return False
        return True

    def get_state(self):
        return {"integrity": self.integrity}
