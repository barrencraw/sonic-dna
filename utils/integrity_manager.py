import os
import json

class IntegrityManager:
    def __init__(self, state_path='data/system_integrity.json'):
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
        else:
            self.integrity = 100

    def save(self):
        # We ensure data folder exists
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        with open(self.state_path, 'w', encoding='utf-8') as f:
            json.dump({'integrity': self.integrity}, f)

    def process_dna(self, rule_name, values):
        """
        Applies drain/restore logic based on DNA values.
        Returns a tuple (integrity_delta, is_refused).
        """
        if rule_name != "Texture Complexity":
            # Other rules don't affect integrity for now
            return (0, False)

        scarcity = values.get('scarcity', 0)
        layering = values.get('layering', 0)
        variation = values.get('variation', 0)

        is_maintenance = scarcity > 9000
        is_complex = layering > 500 or variation > 7000

        # Refusal check: If integrity is 0 and it's not a maintenance string, refuse.
        if self.integrity <= 0 and not is_maintenance:
            return (0, True)

        delta = 0
        if is_maintenance:
            delta = 5
        elif is_complex:
            delta = -10

        old_integrity = self.integrity
        self.integrity = max(0, min(100, self.integrity + delta))

        return (self.integrity - old_integrity, False)
