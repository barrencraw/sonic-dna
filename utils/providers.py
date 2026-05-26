try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    import random
    HAS_NUMPY = False

class RngProvider:
    """
    Deterministic RNG Provider wrapping numpy's default_rng or standard random.
    """
    def __init__(self, seed=None):
        self._seed = seed
        self.set_seed(seed)

    def set_seed(self, seed):
        self._seed = seed
        if HAS_NUMPY:
            self._rng = np.random.default_rng(seed)
        else:
            self._rng = random.Random(seed)

    def uniform(self, low=0.0, high=1.0, size=None):
        if HAS_NUMPY:
            return self._rng.uniform(low, high, size)
        if size is not None:
            return [self._rng.uniform(low, high) for _ in range(size)]
        return self._rng.uniform(low, high)

    def standard_normal(self, size=None):
        if HAS_NUMPY:
            return self._rng.standard_normal(size)
        if size is not None:
            return [self._rng.gauss(0.0, 1.0) for _ in range(size)]
        return self._rng.gauss(0.0, 1.0)

    def normal(self, loc=0.0, scale=1.0, size=None):
        if HAS_NUMPY:
            return self._rng.normal(loc, scale, size)
        if size is not None:
            return [self._rng.gauss(loc, scale) for _ in range(size)]
        return self._rng.gauss(loc, scale)
