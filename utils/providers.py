from unittest.mock import MagicMock

try:
    import numpy as np
    HAS_NUMPY = not isinstance(np, MagicMock)
except ImportError:
    HAS_NUMPY = False
    np = None

class RngProvider:
    """
    Deterministic RNG Provider wrapping numpy's default_rng when available.
    """
    def __init__(self, seed=None):
        self.set_seed(seed)

    def set_seed(self, seed):
        if HAS_NUMPY and np is not None:
            self._rng = np.random.default_rng(seed)
        else:
            self._rng = None

    def uniform(self, low=0.0, high=1.0, size=None):
        if self._rng is not None:
            return self._rng.uniform(low, high, size)
        return 0.5

    def standard_normal(self, size=None):
        if self._rng is not None:
            return self._rng.standard_normal(size)
        return 0.0

    def normal(self, loc=0.0, scale=1.0, size=None):
        if self._rng is not None:
            return self._rng.normal(loc, scale, size)
        return loc
