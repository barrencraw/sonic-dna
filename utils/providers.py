try:
    import numpy as np
except ImportError:
    import random
    class np_mock:
        class random:
            @staticmethod
            def default_rng(seed=None):
                return random.Random(seed)
    np = np_mock

class RngProvider:
    """
    Deterministic RNG Provider wrapping numpy's default_rng if available,
    falling back to standard random.
    """
    def __init__(self, seed=None):
        self.set_seed(seed)

    def set_seed(self, seed):
        if hasattr(np.random, 'default_rng'):
            self._rng = np.random.default_rng(seed)
        else:
            self._rng = random.Random(seed)

    def uniform(self, low=0.0, high=1.0, size=None):
        if hasattr(self._rng, 'uniform'):
            return self._rng.uniform(low, high) # numpy/random both have uniform
        return self._rng.uniform(low, high)

    def standard_normal(self, size=None):
        if hasattr(self._rng, 'standard_normal'):
            return self._rng.standard_normal(size)
        return self._rng.gauss(0, 1)

    def normal(self, loc=0.0, scale=1.0, size=None):
        if hasattr(self._rng, 'normal'):
            return self._rng.normal(loc, scale, size)
        return self._rng.gauss(loc, scale)
