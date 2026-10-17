from unittest.mock import MagicMock

try:
    import numpy as np
    if isinstance(np, MagicMock):
        HAS_NUMPY = False
    else:
        HAS_NUMPY = True
except ImportError:
    np = None
    HAS_NUMPY = False

import random

class RngProvider:
    """
    Deterministic RNG Provider wrapping numpy's default_rng if available,
    falling back to standard random.Random.
    """
    def __init__(self, seed=None):
        self.seed = seed
        self.set_seed(seed)

    def set_seed(self, seed):
        self.seed = seed
        if HAS_NUMPY and np is not None:
            self._rng = np.random.default_rng(seed)
        else:
            self._rng = random.Random(seed)

    def uniform(self, low=0.0, high=1.0, size=None):
        if HAS_NUMPY and np is not None:
            return self._rng.uniform(low, high, size)
        if size is None:
            return self._rng.uniform(low, high)
        if isinstance(size, tuple):
            count = 1
            for dim in size:
                count *= dim
            vals = [self._rng.uniform(low, high) for _ in range(count)]
            return vals
        return [self._rng.uniform(low, high) for _ in range(size)]

    def standard_normal(self, size=None):
        if HAS_NUMPY and np is not None:
            return self._rng.standard_normal(size)
        if size is None:
            return self._rng.gauss(0.0, 1.0)
        if isinstance(size, tuple):
            count = 1
            for dim in size:
                count *= dim
            vals = [self._rng.gauss(0.0, 1.0) for _ in range(count)]
            return vals
        return [self._rng.gauss(0.0, 1.0) for _ in range(size)]

    def normal(self, loc=0.0, scale=1.0, size=None):
        if HAS_NUMPY and np is not None:
            return self._rng.normal(loc, scale, size)
        if size is None:
            return self._rng.gauss(loc, scale)
        if isinstance(size, tuple):
            count = 1
            for dim in size:
                count *= dim
            vals = [self._rng.gauss(loc, scale) for _ in range(count)]
            return vals
        return [self._rng.gauss(loc, scale) for _ in range(size)]
