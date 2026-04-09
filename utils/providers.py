import random

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

class RngProvider:
    """
    Deterministic RNG Provider wrapping numpy's default_rng if available,
    otherwise falling back to python's random.Random.
    """
    def __init__(self, seed=None):
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
            elif isinstance(size, int):
                return [self._rng.uniform(low, high) for _ in range(size)]
            else:
                # Handle tuple size for 2D etc if needed, though simple for now
                def _gen(s):
                    if len(s) == 1:
                        return [self._rng.uniform(low, high) for _ in range(s[0])]
                    return [_gen(s[1:]) for _ in range(s[0])]
                return _gen(size)

    def standard_normal(self, size=None):
        if HAS_NUMPY:
            return self._rng.standard_normal(size)
        else:
            if size is None:
                return self._rng.normalvariate(0.0, 1.0)
            elif isinstance(size, int):
                return [self._rng.normalvariate(0.0, 1.0) for _ in range(size)]
            else:
                def _gen(s):
                    if len(s) == 1:
                        return [self._rng.normalvariate(0.0, 1.0) for _ in range(s[0])]
                    return [_gen(s[1:]) for _ in range(s[0])]
                return _gen(size)

    def normal(self, loc=0.0, scale=1.0, size=None):
        if HAS_NUMPY:
            return self._rng.normal(loc, scale, size)
        else:
            if size is None:
                return self._rng.normalvariate(loc, scale)
            elif isinstance(size, int):
                return [self._rng.normalvariate(loc, scale) for _ in range(size)]
            else:
                def _gen(s):
                    if len(s) == 1:
                        return [self._rng.normalvariate(loc, scale) for _ in range(s[0])]
                    return [_gen(s[1:]) for _ in range(s[0])]
                return _gen(size)
