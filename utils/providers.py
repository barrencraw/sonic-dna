try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

class RngProvider:
    """
    Deterministic RNG Provider wrapping numpy's default_rng.
    """
    def __init__(self, seed=None):
        self.set_seed(seed)

    def set_seed(self, seed):
        if HAS_NUMPY:
            self._rng = np.random.default_rng(seed)
        else:
            self._rng = None

    def uniform(self, low=0.0, high=1.0, size=None):
        if self._rng:
            return self._rng.uniform(low, high, size)
        return None

    def standard_normal(self, size=None):
        if self._rng:
            return self._rng.standard_normal(size)
        return None

    def normal(self, loc=0.0, scale=1.0, size=None):
        if self._rng:
            return self._rng.normal(loc, scale, size)
        return None
