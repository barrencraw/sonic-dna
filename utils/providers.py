import random

try:
    import numpy as np
except ImportError:
    np = None

class RngProvider:
    """
    Deterministic RNG Provider.
    Wraps numpy's default_rng if available, otherwise falls back to standard random.
    Note: Sequences will differ between numpy and random even with the same seed.
    """
    def __init__(self, seed=None):
        self.set_seed(seed)

    def set_seed(self, seed):
        if np:
            self._rng = np.random.default_rng(seed)
        else:
            self._rng = random.Random(seed)

    def uniform(self, low=0.0, high=1.0, size=None):
        if np:
            return self._rng.uniform(low, high, size)
        else:
            if size is None:
                return self._rng.uniform(low, high)
            return [self._rng.uniform(low, high) for _ in range(size)]

    def standard_normal(self, size=None):
        if np:
            return self._rng.standard_normal(size)
        else:
            if size is None:
                return self._rng.gauss(0.0, 1.0)
            return [self._rng.gauss(0.0, 1.0) for _ in range(size)]

    def normal(self, loc=0.0, scale=1.0, size=None):
        if np:
            return self._rng.normal(loc, scale, size)
        else:
            if size is None:
                return self._rng.gauss(loc, scale)
            return [self._rng.gauss(loc, scale) for _ in range(size)]
