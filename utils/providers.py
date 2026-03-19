try:
    import numpy as np
except ImportError:
    np = None

class RngProvider:
    """
    Deterministic RNG Provider wrapping numpy's default_rng.
    """
    def __init__(self, seed=None):
        if np:
            self.set_seed(seed)
        else:
            self._rng = None

    def set_seed(self, seed):
        if np:
            self._rng = np.random.default_rng(seed)

    def uniform(self, low=0.0, high=1.0, size=None):
        if self._rng:
            return self._rng.uniform(low, high, size)
        raise RuntimeError("Numpy not available for RNG")

    def standard_normal(self, size=None):
        if self._rng:
            return self._rng.standard_normal(size)
        raise RuntimeError("Numpy not available for RNG")

    def normal(self, loc=0.0, scale=1.0, size=None):
        if self._rng:
            return self._rng.normal(loc, scale, size)
        raise RuntimeError("Numpy not available for RNG")
