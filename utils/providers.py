import random

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    np = None
    HAS_NUMPY = False

class RngProvider:
    """
    Deterministic RNG Provider wrapping numpy's default_rng or Python's built-in random.
    """
    def __init__(self, seed=None):
        self._seed = seed
        self.set_seed(seed)

    def set_seed(self, seed):
        self._seed = seed
        if HAS_NUMPY:
            self._rng = np.random.default_rng(seed)
        else:
            self._py_rng = random.Random(seed)

    def uniform(self, low=0.0, high=1.0, size=None):
        if HAS_NUMPY:
            return self._rng.uniform(low, high, size)
        else:
            if size is None:
                return self._py_rng.uniform(low, high)
            if isinstance(size, tuple):
                count = 1
                for s in size:
                    count *= s
                vals = [self._py_rng.uniform(low, high) for _ in range(count)]
                # Mock minimal array-like object if numpy is absent
                return vals
            return [self._py_rng.uniform(low, high) for _ in range(size)]

    def standard_normal(self, size=None):
        if HAS_NUMPY:
            return self._rng.standard_normal(size)
        else:
            if size is None:
                return self._py_rng.gauss(0, 1)
            if isinstance(size, tuple):
                count = 1
                for s in size:
                    count *= s
                vals = [self._py_rng.gauss(0, 1) for _ in range(count)]
                return vals
            return [self._py_rng.gauss(0, 1) for _ in range(size)]

    def normal(self, loc=0.0, scale=1.0, size=None):
        if HAS_NUMPY:
            return self._rng.normal(loc, scale, size)
        else:
            if size is None:
                return self._py_rng.gauss(loc, scale)
            if isinstance(size, tuple):
                count = 1
                for s in size:
                    count *= s
                vals = [self._py_rng.gauss(loc, scale) for _ in range(count)]
                return vals
            return [self._py_rng.gauss(loc, scale) for _ in range(size)]
