import json
import os

class IntegrityManager:
    def __init__(self, state_path):
        self.state_path = state_path
        self.integrity = 100
        self.load()

    def load(self):
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.integrity = data.get('integrity', 100)
            except Exception:
                self.integrity = 100

    def save_to_dict(self):
        return {'integrity': self.integrity}

    def apply_consequence(self, parsed_dna):
        """
        Applies integrity changes based on DNA structure.
        Returns a message key if a consequence was applied, else None.
        """
        rule = parsed_dna.get('rule')
        values = parsed_dna.get('values', {})

        if rule == "Texture Complexity":
            layering = values.get('layering', 0)
            variation = values.get('variation', 0)
            scarcity = values.get('scarcity', 0)

            # Drain logic
            if layering > 500 or variation > 7000:
                self.integrity = max(0, self.integrity - 10)
                return "consequence_applied"

            # Restore logic
            if scarcity > 9000:
                self.integrity = min(100, self.integrity + 5)
                return "integrity_restored" # Custom key for internal use if needed, but let's stick to the requested ones for UI

        return None

    def can_process(self, parsed_dna):
        """
        Returns True if processing is allowed, False otherwise.
        Maintenance strings (scarcity > 9000) are always allowed if they restore integrity.
        """
        if self.integrity > 0:
            return True

        # Check if it's a maintenance string
        rule = parsed_dna.get('rule')
        values = parsed_dna.get('values', {})
        if rule == "Texture Complexity" and values.get('scarcity', 0) > 9000:
            return True

        return False
