try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    import random
    HAS_NUMPY = False

class RngProvider:
    """
    Deterministic RNG Provider. Wraps numpy's default_rng if available,
    otherwise falls back to python's random.Random.
    """
    def __init__(self, seed=None):
        self.set_seed(seed)

    def set_seed(self, seed):
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
            elif isinstance(size, int):
                return [self._rng.uniform(low, high) for _ in range(size)]
            else:
                # Handle tuple sizes minimally if needed
                import functools
                import operator
                total = functools.reduce(operator.mul, size, 1)
                return [self._rng.uniform(low, high) for _ in range(total)]

    def standard_normal(self, size=None):
        if HAS_NUMPY:
            return self._rng.standard_normal(size)
        else:
            if size is None:
                return self._rng.gauss(0.0, 1.0)
            elif isinstance(size, int):
                return [self._rng.gauss(0.0, 1.0) for _ in range(size)]
            else:
                import functools
                import operator
                total = functools.reduce(operator.mul, size, 1)
                return [self._rng.gauss(0.0, 1.0) for _ in range(total)]

    def normal(self, loc=0.0, scale=1.0, size=None):
        if HAS_NUMPY:
            return self._rng.normal(loc, scale, size)
        else:
            if size is None:
                return self._rng.gauss(loc, scale)
            elif isinstance(size, int):
                return [self._rng.gauss(loc, scale) for _ in range(size)]
            else:
                import functools
                import operator
                total = functools.reduce(operator.mul, size, 1)
                return [self._rng.gauss(loc, scale) for _ in range(total)]
