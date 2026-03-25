import os
import json

class IntegrityManager:
    def __init__(self, state_path):
        self.state_path = state_path
        self.state = self.load_state()

    def load_state(self):
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {"integrity": 100}

    def get_integrity(self):
        return self.state.get("integrity", 100)

    def is_maintenance_dna(self, rule_name, values):
        """
        Maintenance is defined as Texture Complexity with scarcity > 8000.
        """
        if rule_name == "Texture Complexity":
            scarcity = values.get("scarcity", 0)
            return scarcity > 8000
        return False

    def calculate_wear(self, rule_name, values):
        """
        Deterministic wear calculation:
        - Texture Complexity (scarcity < 2000): -5
        - Texture Complexity (scarcity > 8000): +10
        - Others: -2
        """
        if rule_name == "Texture Complexity":
            scarcity = values.get("scarcity", 0)
            if scarcity > 8000:
                return 10
            elif scarcity < 2000:
                return -5
        return -2

    def apply_wear(self, rule_name, values):
        current = self.get_integrity()
        delta = self.calculate_wear(rule_name, values)
        new_val = max(0, min(100, current + delta))
        self.state["integrity"] = new_val
        return delta

    def should_refuse(self, rule_name, values):
        """
        Refuse processing if integrity is 0 and it's NOT maintenance.
        """
        if self.get_integrity() == 0:
            if not self.is_maintenance_dna(rule_name, values):
                return True
        return False
