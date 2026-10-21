try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    np = None
    HAS_NUMPY = False

class RngProvider:
    """
    Deterministic RNG Provider wrapping numpy's default_rng.
    """
    def __init__(self, seed=None):
        if not HAS_NUMPY or np is None:
            raise RuntimeError("numpy is required for RngProvider")
        self.set_seed(seed)

    def set_seed(self, seed):
        if not HAS_NUMPY or np is None:
            raise RuntimeError("numpy is required for RngProvider")
        self._rng = np.random.default_rng(seed)

    def uniform(self, low=0.0, high=1.0, size=None):
        return self._rng.uniform(low, high, size)

    def standard_normal(self, size=None):
        return self._rng.standard_normal(size)

    def normal(self, loc=0.0, scale=1.0, size=None):
        return self._rng.normal(loc, scale, size)
