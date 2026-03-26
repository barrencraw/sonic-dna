import os
import json

class IntegrityManager:
    def __init__(self, state_path):
        self.state_path = state_path
        self.integrity = self._load_integrity()

    def _load_integrity(self):
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('integrity', 100)
            except Exception:
                return 100
        return 100

    def save(self):
        # Note: In the production pipeline, we usually stage this with other files
        # but for individual use or tests, we provide this.
        with open(self.state_path, 'w', encoding='utf-8') as f:
            json.dump({'integrity': self.integrity}, f, indent=2)

    def is_maintenance_dna(self, rule_name, values):
        if rule_name == "Texture Complexity":
            scarcity = values.get('scarcity', 0)
            if scarcity > 8000:
                return True
        return False

    def calculate_wear(self, rule_name, values):
        """
        Deterministic wear calculation:
        - TEX scarcity < 2000: -5 (high density = high stress)
        - TEX scarcity > 8000: +10 (maintenance/sparse)
        - Others: -2 (standard wear)
        """
        if rule_name == "Texture Complexity":
            scarcity = values.get('scarcity', 0)
            if scarcity < 2000:
                return -5
            elif scarcity > 8000:
                return 10
        return -2

    def apply_wear(self, wear):
        self.integrity += wear
        if self.integrity > 100:
            self.integrity = 100
        if self.integrity < 0:
            self.integrity = 0
        return self.integrity

    def can_process(self, rule_name, values):
        """
        Refusal logic:
        If integrity is 0, only maintenance DNA can be processed.
        """
        if self.integrity > 0:
            return True
        return self.is_maintenance_dna(rule_name, values)
