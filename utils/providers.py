import random

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

class RngProvider:
    """
    Deterministic RNG Provider.
    Uses numpy's default_rng if available, otherwise falls back to random.Random.
    """
    def __init__(self, seed=None):
        self.seed = seed
        self.set_seed(seed)

    def set_seed(self, seed):
        self.seed = seed
        if HAS_NUMPY:
            self._rng = np.random.default_rng(seed)
        else:
            self._rng = random.Random(seed)

    def _generate_size(self, size, func):
        """Helper to handle the 'size' parameter for the random fallback."""
        if size is None:
            return func()
        if isinstance(size, int):
            return [func() for _ in range(size)]
        if isinstance(size, tuple):
            # Support nested lists for tuple sizes (e.g., (2, 3))
            def nested(dims):
                if len(dims) == 1:
                    return [func() for _ in range(dims[0])]
                return [nested(dims[1:]) for _ in range(dims[0])]
            return nested(size)
        return func()

    def uniform(self, low=0.0, high=1.0, size=None):
        if HAS_NUMPY:
            return self._rng.uniform(low, high, size)
        return self._generate_size(size, lambda: self._rng.uniform(low, high))

    def standard_normal(self, size=None):
        if HAS_NUMPY:
            return self._rng.standard_normal(size)
        return self._generate_size(size, lambda: self._rng.gauss(0.0, 1.0))

    def normal(self, loc=0.0, scale=1.0, size=None):
        if HAS_NUMPY:
            return self._rng.normal(loc, scale, size)
        return self._generate_size(size, lambda: self._rng.gauss(loc, scale))
