import random

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

class RngProvider:
    """
    Deterministic RNG Provider. Wraps numpy's default_rng if available,
    otherwise falls back to random.Random for basic determinism in test environments.
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
            if isinstance(size, int):
                return [self._rng.uniform(low, high) for _ in range(size)]
            # Simple tuple handling for 2D if needed, but gen_wave mostly uses 1D or None
            if isinstance(size, tuple):
                if len(size) == 1:
                    return [self._rng.uniform(low, high) for _ in range(size[0])]
                # Recursive for multi-dim if absolutely needed
                def gen_rec(s):
                    if len(s) == 1:
                        return [self._rng.uniform(low, high) for _ in range(s[0])]
                    return [gen_rec(s[1:]) for _ in range(s[0])]
                return gen_rec(size)
            return self._rng.uniform(low, high)

    def standard_normal(self, size=None):
        if HAS_NUMPY:
            return self._rng.standard_normal(size)
        else:
            if size is None:
                return self._rng.gauss(0, 1)
            if isinstance(size, int):
                return [self._rng.gauss(0, 1) for _ in range(size)]
            if isinstance(size, tuple):
                def gen_rec(s):
                    if len(s) == 1:
                        return [self._rng.gauss(0, 1) for _ in range(s[0])]
                    return [gen_rec(s[1:]) for _ in range(s[0])]
                return gen_rec(size)
            return self._rng.gauss(0, 1)

    def normal(self, loc=0.0, scale=1.0, size=None):
        if HAS_NUMPY:
            return self._rng.normal(loc, scale, size)
        else:
            if size is None:
                return self._rng.gauss(loc, scale)
            if isinstance(size, int):
                return [self._rng.gauss(loc, scale) for _ in range(size)]
            if isinstance(size, tuple):
                def gen_rec(s):
                    if len(s) == 1:
                        return [self._rng.gauss(loc, scale) for _ in range(s[0])]
                    return [gen_rec(s[1:]) for _ in range(s[0])]
                return gen_rec(size)
            return self._rng.gauss(loc, scale)
