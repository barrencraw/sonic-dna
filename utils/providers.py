try:
    import numpy as np
    HAS_NUMPY = True
except Exception:
    np = None
    HAS_NUMPY = False

class RngProvider:
    """
    Deterministic RNG Provider wrapping numpy's default_rng.
    """
    def __init__(self, seed=None):
        if HAS_NUMPY and hasattr(np, 'random') and hasattr(np.random, 'default_rng'):
            self.set_seed(seed)
        else:
            self._rng = None

    def set_seed(self, seed):
        if HAS_NUMPY and hasattr(np, 'random') and hasattr(np.random, 'default_rng'):
            self._rng = np.random.default_rng(seed)

    def uniform(self, low=0.0, high=1.0, size=None):
        if self._rng:
            return self._rng.uniform(low, high, size)
        return 0.5

    def standard_normal(self, size=None):
        if self._rng:
            return self._rng.standard_normal(size)
        return 0.0

    def normal(self, loc=0.0, scale=1.0, size=None):
        if self._rng:
            return self._rng.normal(loc, scale, size)
        return loc
