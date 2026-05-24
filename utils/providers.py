try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    import random

class RngProvider:
    """
    Deterministic RNG Provider wrapping numpy's default_rng.
    Falls back to 'random' if numpy is missing.
    """
    def __init__(self, seed=None):
        self._seed = seed
        self.set_seed(seed)

    def set_seed(self, seed):
        self._seed = seed
        if HAS_NUMPY:
            self._rng = np.random.default_rng(seed)
        else:
            random.seed(seed)

    def uniform(self, low=0.0, high=1.0, size=None):
        if HAS_NUMPY:
            return self._rng.uniform(low, high, size)
        if size is not None:
            return [random.uniform(low, high) for _ in range(size)]
        return random.uniform(low, high)

    def standard_normal(self, size=None):
        if HAS_NUMPY:
            return self._rng.standard_normal(size)
        # Simple Box-Muller fallback for standard normal
        def bm():
            import math
            u1 = random.random()
            u2 = random.random()
            return math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)

        if size is not None:
            return [bm() for _ in range(size)]
        return bm()

    def normal(self, loc=0.0, scale=1.0, size=None):
        if HAS_NUMPY:
            return self._rng.normal(loc, scale, size)
        sn = self.standard_normal(size)
        if size is not None:
            return [loc + scale * x for x in sn]
        return loc + scale * sn
