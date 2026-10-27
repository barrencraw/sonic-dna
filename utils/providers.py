import random

try:
    import numpy as np
except ImportError:
    np = None

class RngProvider:
    """
    Deterministic RNG Provider wrapping numpy's default_rng or falling back to random.Random.
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
        if np is not None and hasattr(self._rng, 'uniform'):
            return self._rng.uniform(low, high, size)
        if size is None:
            return self._rng.uniform(low, high)
        if isinstance(size, tuple):
            total = 1
            for dim in size:
                total *= dim
            vals = [self._rng.uniform(low, high) for _ in range(total)]
            return vals
        return [self._rng.uniform(low, high) for _ in range(size)]

    def standard_normal(self, size=None):
        if np is not None and hasattr(self._rng, 'standard_normal'):
            return self._rng.standard_normal(size)
        if size is None:
            return self._rng.normalvariate(0, 1)
        if isinstance(size, tuple):
            total = 1
            for dim in size:
                total *= dim
            return [self._rng.normalvariate(0, 1) for _ in range(total)]
        return [self._rng.normalvariate(0, 1) for _ in range(size)]

    def normal(self, loc=0.0, scale=1.0, size=None):
        if np is not None and hasattr(self._rng, 'normal'):
            return self._rng.normal(loc, scale, size)
        if size is None:
            return self._rng.normalvariate(loc, scale)
        if isinstance(size, tuple):
            total = 1
            for dim in size:
                total *= dim
            return [self._rng.normalvariate(loc, scale) for _ in range(total)]
        return [self._rng.normalvariate(loc, scale) for _ in range(size)]
