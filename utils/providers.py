import random

try:
    import numpy as np
except ImportError:
    np = None

class RngProvider:
    """
    Deterministic RNG Provider wrapping numpy's default_rng or Python's random.Random.
    """
    def __init__(self, seed=None):
        self.set_seed(seed)

    def set_seed(self, seed):
        self.seed = seed
        if np is not None:
            self._rng = np.random.default_rng(seed)
        else:
            self._rng = random.Random(seed)

    def uniform(self, low=0.0, high=1.0, size=None):
        if np is not None:
            return self._rng.uniform(low, high, size)
        if size is None:
            return self._rng.uniform(low, high)
        if isinstance(size, tuple):
            if len(size) == 1:
                return [self._rng.uniform(low, high) for _ in range(size[0])]
            elif len(size) == 2:
                return [[self._rng.uniform(low, high) for _ in range(size[1])] for _ in range(size[0])]
        return [self._rng.uniform(low, high) for _ in range(size)]

    def standard_normal(self, size=None):
        if np is not None:
            return self._rng.standard_normal(size)
        if size is None:
            return self._rng.gauss(0, 1)
        if isinstance(size, tuple):
            if len(size) == 1:
                return [self._rng.gauss(0, 1) for _ in range(size[0])]
            elif len(size) == 2:
                return [[self._rng.gauss(0, 1) for _ in range(size[1])] for _ in range(size[0])]
        return [self._rng.gauss(0, 1) for _ in range(size)]

    def normal(self, loc=0.0, scale=1.0, size=None):
        if np is not None:
            return self._rng.normal(loc, scale, size)
        if size is None:
            return self._rng.gauss(loc, scale)
        if isinstance(size, tuple):
            if len(size) == 1:
                return [self._rng.gauss(loc, scale) for _ in range(size[0])]
            elif len(size) == 2:
                return [[self._rng.gauss(loc, scale) for _ in range(size[1])] for _ in range(size[0])]
        return [self._rng.gauss(loc, scale) for _ in range(size)]
