import random

try:
    import numpy as np
except ImportError:
    np = None


class RngProvider:
    """
    Deterministic RNG Provider wrapping numpy's default_rng if available,
    falling back to Python's built-in random.Random.
    """
    def __init__(self, seed=None):
        self.set_seed(seed)

    def set_seed(self, seed):
        self._seed = seed
        if np is not None:
            self._rng = np.random.default_rng(seed)
        else:
            self._rng = random.Random(seed)

    def uniform(self, low=0.0, high=1.0, size=None):
        if np is not None and isinstance(self._rng, np.random.Generator):
            return self._rng.uniform(low, high, size)
        else:
            if size is None:
                return self._rng.uniform(low, high)
            if isinstance(size, (list, tuple)):
                import functools, operator
                total = functools.reduce(operator.mul, size, 1)
                return [self._rng.uniform(low, high) for _ in range(total)]
            return [self._rng.uniform(low, high) for _ in range(size)]

    def standard_normal(self, size=None):
        if np is not None and isinstance(self._rng, np.random.Generator):
            return self._rng.standard_normal(size)
        else:
            if size is None:
                return self._rng.gauss(0, 1)
            if isinstance(size, (list, tuple)):
                import functools, operator
                total = functools.reduce(operator.mul, size, 1)
                return [self._rng.gauss(0, 1) for _ in range(total)]
            return [self._rng.gauss(0, 1) for _ in range(size)]

    def normal(self, loc=0.0, scale=1.0, size=None):
        if np is not None and isinstance(self._rng, np.random.Generator):
            return self._rng.normal(loc, scale, size)
        else:
            if size is None:
                return self._rng.gauss(loc, scale)
            if isinstance(size, (list, tuple)):
                import functools, operator
                total = functools.reduce(operator.mul, size, 1)
                return [self._rng.gauss(loc, scale) for _ in range(total)]
            return [self._rng.gauss(loc, scale) for _ in range(size)]
