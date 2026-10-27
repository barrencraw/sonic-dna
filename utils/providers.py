try:
    import numpy as np
except ImportError:
    np = None

class RngProvider:
    """
    Deterministic RNG Provider wrapping numpy's default_rng if available,
    or random.Random as fallback.
    """
    def __init__(self, seed=None):
        self.set_seed(seed)

    def set_seed(self, seed):
        if np is not None:
            self._rng = np.random.default_rng(seed)
        else:
            import random
            self._rng = random.Random(seed)

    def uniform(self, low=0.0, high=1.0, size=None):
        if np is not None:
            return self._rng.uniform(low, high, size)
        else:
            if size is None:
                return self._rng.uniform(low, high)
            elif isinstance(size, tuple):
                import math
                total = math.prod(size)
                return [self._rng.uniform(low, high) for _ in range(total)]
            else:
                return [self._rng.uniform(low, high) for _ in range(size)]

    def standard_normal(self, size=None):
        if np is not None:
            return self._rng.standard_normal(size)
        else:
            if size is None:
                return self._rng.gauss(0, 1)
            elif isinstance(size, tuple):
                import math
                total = math.prod(size)
                return [self._rng.gauss(0, 1) for _ in range(total)]
            else:
                return [self._rng.gauss(0, 1) for _ in range(size)]

    def normal(self, loc=0.0, scale=1.0, size=None):
        if np is not None:
            return self._rng.normal(loc, scale, size)
        else:
            if size is None:
                return self._rng.gauss(loc, scale)
            elif isinstance(size, tuple):
                import math
                total = math.prod(size)
                return [self._rng.gauss(loc, scale) for _ in range(total)]
            else:
                return [self._rng.gauss(loc, scale) for _ in range(size)]
