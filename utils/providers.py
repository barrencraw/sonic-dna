import random

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

class RngProvider:
    """
    Deterministic RNG Provider.
    Uses numpy.random.default_rng if available, falls back to standard random.
    NOTE: Random number sequences WILL diverge between numpy and random implementations.
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
            else:
                # size is a tuple, e.g. (2, 3)
                def fill(s):
                    if len(s) == 1:
                        return [self._rng.uniform(low, high) for _ in range(s[0])]
                    return [fill(s[1:]) for _ in range(s[0])]
                return fill(size)

    def standard_normal(self, size=None):
        if HAS_NUMPY:
            return self._rng.standard_normal(size)
        else:
            if size is None:
                return self._rng.gauss(0.0, 1.0)
            elif isinstance(size, int):
                return [self._rng.gauss(0.0, 1.0) for _ in range(size)]
            else:
                def fill(s):
                    if len(s) == 1:
                        return [self._rng.gauss(0.0, 1.0) for _ in range(s[0])]
                    return [fill(s[1:]) for _ in range(s[0])]
                return fill(size)

    def normal(self, loc=0.0, scale=1.0, size=None):
        if HAS_NUMPY:
            return self._rng.normal(loc, scale, size)
        else:
            if size is None:
                return self._rng.gauss(loc, scale)
            elif isinstance(size, int):
                return [self._rng.gauss(loc, scale) for _ in range(size)]
            else:
                def fill(s):
                    if len(s) == 1:
                        return [self._rng.gauss(loc, scale) for _ in range(s[0])]
                    return [fill(s[1:]) for _ in range(s[0])]
                return fill(size)
