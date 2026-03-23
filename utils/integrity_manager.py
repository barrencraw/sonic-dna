import os
import json

class IntegrityManager:
    def __init__(self, integrity_path, max_integrity=100):
        self.integrity_path = integrity_path
        self.max_integrity = max_integrity
        self.integrity = self._load_integrity()

    def _load_integrity(self):
        if os.path.exists(self.integrity_path):
            try:
                with open(self.integrity_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('integrity', self.max_integrity)
            except Exception:
                return self.max_integrity
        return self.max_integrity

    def is_maintenance_dna(self, rule_name, values):
        """
        Returns True if the DNA is a maintenance string.
        """
        if rule_name == "Texture Complexity":
            scarcity = values.get('scarcity', 0)
            if scarcity > 8000:
                return True
        return False

    def calculate_wear(self, rule_name, values):
        """
        Determines the change in integrity based on the rule and parsed values.
        """
        delta = -2 # Standard wear

        if rule_name == "Texture Complexity":
            scarcity = values.get('scarcity', 0)
            if self.is_maintenance_dna(rule_name, values):
                delta = 10 # Maintenance
            elif scarcity < 2000:
                delta = -5 # High-complexity drain

        return delta

    def apply_delta(self, delta):
        new_integrity = self.integrity + delta
        self.integrity = max(0, min(self.max_integrity, new_integrity))
        return self.integrity

    def to_dict(self):
        return {"integrity": self.integrity}
