try:
    import numpy as np
    HAS_NUMPY = not hasattr(np, '_is_protocol') and not type(np).__name__ == 'MagicMock'
except Exception:
    HAS_NUMPY = False
    np = None

import random

class RngProvider:
    """
    Deterministic RNG Provider wrapping numpy's default_rng or fallback random.
    """
    def __init__(self, seed=None):
        self.set_seed(seed)

    def set_seed(self, seed):
        if HAS_NUMPY and np is not None:
            self._rng = np.random.default_rng(seed)
        else:
            self._rng = random.Random(seed)

    def uniform(self, low=0.0, high=1.0, size=None):
        if HAS_NUMPY and hasattr(self._rng, 'uniform'):
            return self._rng.uniform(low, high, size)
        if size is None:
            return self._rng.uniform(low, high)
        return [self._rng.uniform(low, high) for _ in range(size)]

    def standard_normal(self, size=None):
        if HAS_NUMPY and hasattr(self._rng, 'standard_normal'):
            return self._rng.standard_normal(size)
        if size is None:
            return self._rng.gauss(0.0, 1.0)
        return [self._rng.gauss(0.0, 1.0) for _ in range(size)]

    def normal(self, loc=0.0, scale=1.0, size=None):
        if HAS_NUMPY and hasattr(self._rng, 'normal'):
            return self._rng.normal(loc, scale, size)
        if size is None:
            return self._rng.gauss(loc, scale)
        return [self._rng.gauss(loc, scale) for _ in range(size)]
