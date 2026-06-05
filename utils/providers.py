try:
    import numpy as np
    HAS_NP = True
except ImportError:
    HAS_NP = False
import random

class RngProvider:
    """
    Deterministic RNG Provider wrapping numpy's default_rng.
    Falls back to Python's random if numpy is not available.
    """
    def __init__(self, seed=None):
        self.set_seed(seed)

    def set_seed(self, seed):
        if HAS_NP:
            self._rng = np.random.default_rng(seed)
        else:
            self._rng = random.Random(seed)

    def uniform(self, low=0.0, high=1.0, size=None):
        if HAS_NP:
            return self._rng.uniform(low, high, size)
        else:
            if size is not None:
                return [self._rng.uniform(low, high) for _ in range(size)]
            return self._rng.uniform(low, high)

    def random(self):
        if HAS_NP:
            return self._rng.random()
        else:
            return self._rng.random()

    def standard_normal(self, size=None):
        if HAS_NP:
            return self._rng.standard_normal(size)
        else:
            if size is not None:
                return [self._rng.gauss(0, 1) for _ in range(size)]
            return self._rng.gauss(0, 1)

    def normal(self, loc=0.0, scale=1.0, size=None):
        if HAS_NP:
            return self._rng.normal(loc, scale, size)
        else:
            if size is not None:
                return [self._rng.gauss(loc, scale) for _ in range(size)]
            return self._rng.gauss(loc, scale)
