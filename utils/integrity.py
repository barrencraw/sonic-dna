import os
import json
import tempfile

class IntegrityManager:
    def __init__(self, state_file='data/system_integrity.json'):
        self.state_file = state_file
        self.integrity = self._load_state()

    def _load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('integrity', 100)
            except Exception:
                return 100
        return 100

    def save_state(self):
        """Atomic write of system integrity state."""
        directory = os.path.dirname(self.state_file)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)

        with tempfile.TemporaryDirectory(dir=directory or '.') as tmp_dir:
            tmp_path = os.path.join(tmp_dir, 'integrity.json')
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump({'integrity': self.integrity}, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.state_file)

    def is_maintenance(self, parsed_dna):
        """
        Maintenance DNA: TEX rule and scarcity < 1000.
        """
        if parsed_dna.get('rule') == 'Texture Complexity':
            scarcity = parsed_dna.get('values', {}).get('scarcity', 10000)
            return scarcity < 1000
        return False

    def can_process(self, parsed_dna):
        """
        Can process if integrity > 0 OR if it's a maintenance string.
        """
        if self.integrity > 0:
            return True
        return self.is_maintenance(parsed_dna)

    def apply_wear(self, parsed_dna):
        """
        Normal wear: -2
        Heavy Load (TEX scarcity > 8000): -5
        Maintenance (TEX scarcity < 1000): +10
        Capped at 100, minimum 0.
        Returns the change value.
        """
        change = -2
        if parsed_dna.get('rule') == 'Texture Complexity':
            scarcity = parsed_dna.get('values', {}).get('scarcity', 0)
            if scarcity > 8000:
                change = -5
            elif scarcity < 1000:
                change = 10

        old_integrity = self.integrity
        self.integrity = max(0, min(100, self.integrity + change))
        actual_change = self.integrity - old_integrity
        return actual_change
