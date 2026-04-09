import os
import json
import tempfile

class IntegrityManager:
    def __init__(self, state_path='data/system_integrity.json'):
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

    def save_state(self):
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        with tempfile.TemporaryDirectory(dir=os.path.dirname(self.state_path)) as tmp_dir:
            tmp_file = os.path.join(tmp_dir, 'integrity.json')
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump({'integrity': self.integrity}, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, self.state_path)

    def is_maintenance(self, rule_name, values):
        # TEX rule AND scarcity < 1000
        if rule_name == "Texture Complexity":
            scarcity = values.get('scarcity', 10000)
            if scarcity < 1000:
                return True
        return False

    def can_process(self, dna_str, rule_name=None, values=None):
        if self.integrity > 0:
            return True
        # If integrity is 0, only maintenance is allowed
        if rule_name and values:
            return self.is_maintenance(rule_name, values)
        return False

    def apply_wear(self, dna_str):
        # Baseline wear is 5%. High complexity could be more, but keep it simple for MVP.
        prev = self.integrity
        self.integrity = max(0, self.integrity - 5)
        self.save_state()
        return self.integrity - prev

    def apply_maintenance(self, dna_str):
        prev = self.integrity
        self.integrity = min(100, self.integrity + 20)
        self.save_state()
        return self.integrity - prev
