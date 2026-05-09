try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

import random

class RngProvider:
    """
    Deterministic RNG Provider wrapping numpy's default_rng if available,
    otherwise falls back to standard random.
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
        else:
            if size is None:
                return self._rng.uniform(low, high)
            if isinstance(size, int):
                return [self._rng.uniform(low, high) for _ in range(size)]
            # For multidimensional size, we'd need more complex logic,
            # but basic support for now.
            return [self._rng.uniform(low, high) for _ in range(sum(size) if isinstance(size, tuple) else size)]

    def standard_normal(self, size=None):
        if HAS_NUMPY:
            return self._rng.standard_normal(size)
        else:
            if size is None:
                return self._rng.gauss(0, 1)
            # Not fully compatible with numpy return types but works for existence check
            return [self._rng.gauss(0, 1) for _ in range(size if isinstance(size, int) else 1)]

    def normal(self, loc=0.0, scale=1.0, size=None):
        if HAS_NUMPY:
            return self._rng.normal(loc, scale, size)
        else:
            if size is None:
                return self._rng.gauss(loc, scale)
            return [self._rng.gauss(loc, scale) for _ in range(size if isinstance(size, int) else 1)]
