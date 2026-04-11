import os
import json
import tempfile

class IntegrityManager:
    def __init__(self, integrity_path):
        self.integrity_path = integrity_path
        self.integrity = self._load()

    def _load(self):
        if os.path.exists(self.integrity_path):
            try:
                with open(self.integrity_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('integrity', 100)
            except (json.JSONDecodeError, KeyError):
                return 100
        return 100

    def save(self, target_dir=None):
        """
        Saves integrity state. If target_dir is provided, it uses it for atomic staging.
        """
        data = {'integrity': self.integrity}
        if target_dir:
            tmp_path = os.path.join(target_dir, 'system_integrity.json')
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.integrity_path)
        else:
            with open(self.integrity_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)

    def is_high_complexity(self, dna_result):
        if dna_result.get('rule') == 'Texture Complexity':
            scarcity = dna_result.get('values', {}).get('scarcity', 0)
            return scarcity > 5000
        return False

    def is_maintenance(self, dna_result):
        if dna_result.get('rule') == 'Texture Complexity':
            scarcity = dna_result.get('values', {}).get('scarcity', 0)
            return scarcity < 1000
        return False

    def can_process(self, dna_result):
        if self.is_maintenance(dna_result):
            return True
        if self.is_high_complexity(dna_result):
            return self.integrity >= 10
        return self.integrity > 0

    def apply_wear(self, dna_result):
        if self.is_maintenance(dna_result):
            change = 20
        elif self.is_high_complexity(dna_result):
            change = -5
        else:
            change = -1

        old_integrity = self.integrity
        self.integrity = max(0, min(100, self.integrity + change))
        return self.integrity - old_integrity
