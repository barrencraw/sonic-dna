try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    import random

class RngProvider:
    """
    Deterministic RNG Provider. Wraps numpy's default_rng if available,
    otherwise falls back to python's built-in random module.
    """
    def __init__(self, seed=None):
        self.set_seed(seed)

    def set_seed(self, seed):
        if NUMPY_AVAILABLE:
            self._rng = np.random.default_rng(seed)
        else:
            self._rng = random.Random(seed)

    def uniform(self, low=0.0, high=1.0, size=None):
        if NUMPY_AVAILABLE:
            return self._rng.uniform(low, high, size)
        else:
            if size is not None:
                return [self._rng.uniform(low, high) for _ in range(size)]
            return self._rng.uniform(low, high)

    def standard_normal(self, size=None):
        if NUMPY_AVAILABLE:
            return self._rng.standard_normal(size)
        else:
            if size is not None:
                return [self._rng.gauss(0, 1) for _ in range(size)]
            return self._rng.gauss(0, 1)

    def normal(self, loc=0.0, scale=1.0, size=None):
        if NUMPY_AVAILABLE:
            return self._rng.normal(loc, scale, size)
        else:
            if size is not None:
                return [self._rng.gauss(loc, scale) for _ in range(size)]
            return self._rng.gauss(loc, scale)
