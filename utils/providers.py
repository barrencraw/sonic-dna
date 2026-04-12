import random

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

class RngProvider:
    """
    Deterministic RNG Provider wrapping numpy's default_rng with a random.Random fallback.
    """
    def __init__(self, seed=None):
        self.set_seed(seed)

    def set_seed(self, seed):
        self.seed = seed
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
            else: # Tuple size
                return self._generate_nested_list(self._rng.uniform, (low, high), size)

    def standard_normal(self, size=None):
        if HAS_NUMPY:
            return self._rng.standard_normal(size)
        else:
            if size is None:
                return self._rng.gauss(0.0, 1.0)
            elif isinstance(size, int):
                return [self._rng.gauss(0.0, 1.0) for _ in range(size)]
            else:
                return self._generate_nested_list(self._rng.gauss, (0.0, 1.0), size)

    def normal(self, loc=0.0, scale=1.0, size=None):
        if HAS_NUMPY:
            return self._rng.normal(loc, scale, size)
        else:
            if size is None:
                return self._rng.gauss(loc, scale)
            elif isinstance(size, int):
                return [self._rng.gauss(loc, scale) for _ in range(size)]
            else:
                return self._generate_nested_list(self._rng.gauss, (loc, scale), size)

    def _generate_nested_list(self, func, args, size):
        if len(size) == 1:
            return [func(*args) for _ in range(size[0])]
        else:
            return [self._generate_nested_list(func, args, size[1:]) for _ in range(size[0])]
