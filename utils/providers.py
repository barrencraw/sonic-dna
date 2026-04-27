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
        if HAS_NUMPY:
            self.set_seed(seed)
        else:
            self._rng = None

    def set_seed(self, seed):
        if not HAS_NUMPY:
            raise ImportError("numpy is required for RngProvider")
        self._rng = np.random.default_rng(seed)

    def uniform(self, low=0.0, high=1.0, size=None):
        if not HAS_NUMPY:
            raise ImportError("numpy is required for RngProvider")
        return self._rng.uniform(low, high, size)

    def standard_normal(self, size=None):
        if not HAS_NUMPY:
            raise ImportError("numpy is required for RngProvider")
        return self._rng.standard_normal(size)

    def normal(self, loc=0.0, scale=1.0, size=None):
        if not HAS_NUMPY:
            raise ImportError("numpy is required for RngProvider")
        return self._rng.normal(loc, scale, size)
