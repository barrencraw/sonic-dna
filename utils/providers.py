import random

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

class RngProvider:
    """
    Deterministic RNG Provider wrapping numpy's default_rng if available,
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
            if size is not None:
                if isinstance(size, tuple):
                    # Handle 2D if needed for pink noise fallback
                    res = []
                    for _ in range(size[0]):
                        res.append([self._rng.uniform(low, high) for _ in range(size[1])])
                    return res
                return [self._rng.uniform(low, high) for _ in range(size)]
            return self._rng.uniform(low, high)

    def standard_normal(self, size=None):
        if HAS_NUMPY:
            return self._rng.standard_normal(size)
        else:
            if size is not None:
                if isinstance(size, tuple):
                    # Handle 2D if needed for pink noise fallback
                    res = []
                    for _ in range(size[0]):
                        res.append([self._rng.normalvariate(0, 1) for _ in range(size[1])])
                    return res
                return [self._rng.normalvariate(0, 1) for _ in range(size)]
            return self._rng.normalvariate(0, 1)

    def normal(self, loc=0.0, scale=1.0, size=None):
        if HAS_NUMPY:
            return self._rng.normal(loc, scale, size)
        else:
            if size is not None:
                if isinstance(size, tuple):
                    res = []
                    for _ in range(size[0]):
                        res.append([self._rng.normalvariate(loc, scale) for _ in range(size[1])])
                    return res
                return [self._rng.normalvariate(loc, scale) for _ in range(size)]
            return self._rng.normalvariate(loc, scale)
