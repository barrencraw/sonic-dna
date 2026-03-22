class IntegrityManager:
    def __init__(self, initial_integrity=100):
        self.integrity = initial_integrity

    def calculate_wear(self, dna_result):
        """
        Calculates wear or restoration based on DNA parsing result.
        TEX scarcity < 2000 drains 5.
        TEX scarcity > 8000 restores 10 (cap 100).
        All others drain 2.
        """
        if not dna_result or 'rule' not in dna_result or 'values' not in dna_result:
            # Standard wear for non-parsing events or unknown strings
            self.integrity = max(0, self.integrity - 2)
            return -2

        rule = dna_result.get('rule')
        values = dna_result.get('values', {})

        if rule == 'Texture Complexity':
            scarcity = values.get('scarcity', 5000) # Default mid-point
            if scarcity > 8000:
                old_integrity = self.integrity
                self.integrity = min(100, self.integrity + 10)
                return self.integrity - old_integrity
            elif scarcity < 2000:
                self.integrity = max(0, self.integrity - 5)
                return -5

        # Standard wear
        self.integrity = max(0, self.integrity - 2)
        return -2

    def is_refusing(self, dna_result=None):
        """
        Refusal check: if integrity is 0, only maintenance strings (TEX scarcity > 8000) are allowed.
        """
        if self.integrity > 0:
            return False

        if dna_result and dna_result.get('rule') == 'Texture Complexity':
            scarcity = dna_result.get('values', {}).get('scarcity', 0)
            if scarcity > 8000:
                return False # Maintenance allowed even at 0 integrity

        return True

    def to_dict(self):
        return {"integrity": self.integrity}

    @classmethod
    def from_dict(cls, data):
        return cls(initial_integrity=data.get("integrity", 100))
