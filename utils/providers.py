try:
    import numpy as np
except (ImportError, ModuleNotFoundError):
    import random

    class MockNumpyRng:
        def __init__(self, seed=None):
            self._rng = random.Random(seed)

        def uniform(self, low=0.0, high=1.0, size=None):
            if size is None:
                return self._rng.uniform(low, high)
            return [self._rng.uniform(low, high) for _ in range(size if isinstance(size, int) else size[0])]

        def standard_normal(self, size=None):
            if size is None:
                return self._rng.gauss(0, 1)
            return [self._rng.gauss(0, 1) for _ in range(size if isinstance(size, int) else size[0])]

        def normal(self, loc=0.0, scale=1.0, size=None):
            if size is None:
                return self._rng.gauss(loc, scale)
            return [self._rng.gauss(loc, scale) for _ in range(size if isinstance(size, int) else size[0])]

    class MockNumpy:
        class random:
            @staticmethod
            def default_rng(seed=None):
                return MockNumpyRng(seed)

    np = MockNumpy()

class RngProvider:
    """
    Deterministic RNG Provider wrapping numpy's default_rng.
    """
    def __init__(self, seed=None):
        self.set_seed(seed)

    def set_seed(self, seed):
        self._rng = np.random.default_rng(seed)

    def uniform(self, low=0.0, high=1.0, size=None):
        return self._rng.uniform(low, high, size)

    def standard_normal(self, size=None):
        return self._rng.standard_normal(size)

    def normal(self, loc=0.0, scale=1.0, size=None):
        return self._rng.normal(loc, scale, size)
