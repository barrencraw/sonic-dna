try:
    import numpy as np
except ImportError:
    np = None

class RngProvider:
    """
    Deterministic RNG Provider wrapping numpy's default_rng.
    """
    def __init__(self, seed=None):
        if np is None:
            # Fallback or raise error if required
            pass
        else:
            self.set_seed(seed)

    def set_seed(self, seed):
        if np is not None:
            self._rng = np.random.default_rng(seed)

    def uniform(self, low=0.0, high=1.0, size=None):
        if np is None:
            raise RuntimeError("Numpy not available for RngProvider")
        return self._rng.uniform(low, high, size)

    def standard_normal(self, size=None):
        if np is None:
            raise RuntimeError("Numpy not available for RngProvider")
        return self._rng.standard_normal(size)

    def normal(self, loc=0.0, scale=1.0, size=None):
        if np is None:
            raise RuntimeError("Numpy not available for RngProvider")
        return self._rng.normal(loc, scale, size)
