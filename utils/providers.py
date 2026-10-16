try:
    import numpy as np
except ImportError:
    np = None

class RngProvider:
    """
    Deterministic RNG Provider wrapping numpy's default_rng.
    """
    def __init__(self, seed=None):
        self.set_seed(seed)

    def set_seed(self, seed):
        if np is not None:
            self._rng = np.random.default_rng(seed)
        else:
            self._rng = None

    def uniform(self, low=0.0, high=1.0, size=None):
        if self._rng is not None:
            return self._rng.uniform(low, high, size)
        raise RuntimeError("numpy is required for RngProvider")

    def standard_normal(self, size=None):
        if self._rng is not None:
            return self._rng.standard_normal(size)
        raise RuntimeError("numpy is required for RngProvider")

    def normal(self, loc=0.0, scale=1.0, size=None):
        if self._rng is not None:
            return self._rng.normal(loc, scale, size)
        raise RuntimeError("numpy is required for RngProvider")
