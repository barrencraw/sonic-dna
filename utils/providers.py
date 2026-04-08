import random
import functools

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

class RngProvider:
    """
    Deterministic RNG Provider.
    Wraps numpy's default_rng if available, otherwise falls back to random.Random.
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

            def _generate_nested(shape):
                if not shape:
                    return self._rng.uniform(low, high)
                return [_generate_nested(shape[1:]) for _ in range(shape[0])]

            if isinstance(size, int):
                return [self._rng.uniform(low, high) for _ in range(size)]
            if isinstance(size, tuple):
                return _generate_nested(size)
            return self._rng.uniform(low, high)

    def standard_normal(self, size=None):
        if HAS_NUMPY:
            return self._rng.standard_normal(size)
        else:
            if size is None:
                return self._rng.gauss(0, 1)

            def _generate_nested(shape):
                if not shape:
                    return self._rng.gauss(0, 1)
                return [_generate_nested(shape[1:]) for _ in range(shape[0])]

            if isinstance(size, int):
                return [self._rng.gauss(0, 1) for _ in range(size)]
            if isinstance(size, tuple):
                return _generate_nested(size)
            return self._rng.gauss(0, 1)

    def normal(self, loc=0.0, scale=1.0, size=None):
        if HAS_NUMPY:
            return self._rng.normal(loc, scale, size)
        else:
            if size is None:
                return self._rng.gauss(loc, scale)

            def _generate_nested(shape):
                if not shape:
                    return self._rng.gauss(loc, scale)
                return [_generate_nested(shape[1:]) for _ in range(shape[0])]

            if isinstance(size, int):
                return [self._rng.gauss(loc, scale) for _ in range(size)]
            if isinstance(size, tuple):
                return _generate_nested(size)
            return self._rng.gauss(loc, scale)
