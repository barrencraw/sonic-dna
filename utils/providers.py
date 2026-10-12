try:
    import numpy as np
    from unittest.mock import MagicMock
    HAS_NUMPY = not isinstance(np, MagicMock)
except ImportError:
    np = None
    HAS_NUMPY = False

class RngProvider:
    """
    Deterministic RNG Provider wrapping numpy's default_rng.
    """
    def __init__(self, seed=None):
        if not HAS_NUMPY or np is None:
            self._rng = None
        else:
            self.set_seed(seed)

    def set_seed(self, seed):
        if HAS_NUMPY and np is not None:
            self._rng = np.random.default_rng(seed)

    def uniform(self, low=0.0, high=1.0, size=None):
        if self._rng is not None:
            return self._rng.uniform(low, high, size)
        return []

    def standard_normal(self, size=None):
        if self._rng is not None:
            return self._rng.standard_normal(size)
        return []

    def normal(self, loc=0.0, scale=1.0, size=None):
        if self._rng is not None:
            return self._rng.normal(loc, scale, size)
        return []
