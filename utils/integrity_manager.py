import os
import json

class IntegrityManager:
    def __init__(self, state_path):
        self.state_path = state_path
        self.integrity = self._load_state()

    def _load_state(self):
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, 'r') as f:
                    data = json.load(f)
                    return data.get('integrity', 100)
            except Exception:
                return 100
        return 100

    def apply_consequence(self, dna_parsed):
        """
        Determines and applies the integrity change based on DNA structure.
        TEX Scarcity < 2000: -5
        TEX Scarcity > 8000: +10
        Other: -2
        """
        rule = dna_parsed.get('rule')
        values = dna_parsed.get('values', {})

        change = -2 # Default wear

        if rule == "Texture Complexity":
            scarcity = values.get('scarcity', 5000)
            if scarcity < 2000:
                change = -5
            elif scarcity > 8000:
                change = 10

        old_integrity = self.integrity
        self.integrity = max(0, min(100, self.integrity + change))
        return change, self.integrity

    def can_process(self, dna_parsed):
        """
        Refusal logic: If integrity is 0, only maintenance (TEX Scarcity > 8000) is allowed.
        """
        if self.integrity > 0:
            return True, ""

        rule = dna_parsed.get('rule')
        values = dna_parsed.get('values', {})

        if rule == "Texture Complexity" and values.get('scarcity', 0) > 8000:
            return True, ""

        return False, "System integrity depleted. Maintenance DNA required."

    def get_state(self):
        return {'integrity': self.integrity}
