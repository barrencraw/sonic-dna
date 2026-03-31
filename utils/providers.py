try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    import random
    HAS_NUMPY = False
    import unittest

class RngProvider:
    """
    Deterministic RNG Provider.
    Wraps numpy's default_rng if available, falls back to standard random library.
    """
    def __init__(self, seed=None):
        self.set_seed(seed)

    def set_seed(self, seed):
        self.seed = seed
        if HAS_NUMPY:
            self._rng = np.random.default_rng(seed)
        else:
            random.seed(seed)

    def uniform(self, low=0.0, high=1.0, size=None):
        if HAS_NUMPY:
            return self._rng.uniform(low, high, size)
        else:
            if size is None:
                return random.uniform(low, high)
            return [random.uniform(low, high) for _ in range(size)]

    def standard_normal(self, size=None):
        if HAS_NUMPY:
            return self._rng.standard_normal(size)
        else:
            if size is None:
                return random.gauss(0, 1)
            return [random.gauss(0, 1) for _ in range(size)]

    def normal(self, loc=0.0, scale=1.0, size=None):
        if HAS_NUMPY:
            return self._rng.normal(loc, scale, size)
        else:
            if size is None:
                return random.gauss(loc, scale)
            return [random.gauss(loc, scale) for _ in range(size)]
