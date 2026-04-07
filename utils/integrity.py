import os
import json
import tempfile

class IntegrityManager:
    def __init__(self, state_path='data/system_integrity.json'):
        self.state_path = state_path
        self.integrity = self._load_state()

    def _load_state(self):
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('integrity', 100)
            except (json.JSONDecodeError, Exception):
                return 100
        return 100

    def _save_state(self):
        dir_name = os.path.dirname(self.state_path)
        if dir_name and not os.path.exists(dir_name):
            os.makedirs(dir_name, exist_ok=True)

        with tempfile.TemporaryDirectory(dir=dir_name if dir_name else '.') as tmp_dir:
            tmp_path = os.path.join(tmp_dir, 'integrity.json')
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump({'integrity': self.integrity}, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.state_path)

    def is_maintenance(self, parsed_dna):
        """
        Maintenance DNA is defined as 'Texture Complexity' (TEX)
        with a scarcity value less than 1000.
        """
        if parsed_dna.get('rule') == 'Texture Complexity':
            values = parsed_dna.get('values', {})
            scarcity = values.get('scarcity', 10000)
            if scarcity < 1000:
                return True
        return False

    def can_process(self, parsed_dna):
        """
        Returns False if integrity is 0 and it's not a maintenance string.
        """
        if self.integrity <= 0:
            return self.is_maintenance(parsed_dna)
        return True

    def apply_wear(self, parsed_dna):
        """
        Applies wear or restoration based on the DNA type.
        Returns the integrity change (delta).
        """
        delta = -2 # Normal wear

        if parsed_dna.get('rule') == 'Texture Complexity':
            values = parsed_dna.get('values', {})
            scarcity = values.get('scarcity', 10000)
            if scarcity < 1000:
                delta = 10 # Restoration
            elif scarcity > 8000:
                delta = -5 # Heavy wear

        old_integrity = self.integrity
        self.integrity = max(0, min(100, self.integrity + delta))
        self._save_state()
        return self.integrity - old_integrity
