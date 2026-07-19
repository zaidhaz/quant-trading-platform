"""V1 supports Grid Search and Random Search only — Bayesian search is deliberately
not implemented yet (see docs/ARCHITECTURE.md). Both share the `SearchStrategy`
interface so a future Bayesian implementation is a third class, not a redesign."""

from __future__ import annotations

import itertools
import random
from abc import ABC, abstractmethod
from collections.abc import Callable

ParamSpace = dict[str, list[object]]
ParamSet = dict[str, object]
Evaluate = Callable[[ParamSet], float]


class SearchStrategy(ABC):
    @abstractmethod
    def search(self, param_space: ParamSpace, evaluate: Evaluate) -> list[tuple[ParamSet, float]]:
        """Return (params, score) for every combination tried, sorted best-score-first."""


class GridSearch(SearchStrategy):
    """Exhaustively evaluates every combination in `param_space`."""

    def search(self, param_space: ParamSpace, evaluate: Evaluate) -> list[tuple[ParamSet, float]]:
        keys = list(param_space)
        results: list[tuple[ParamSet, float]] = []
        for combo in itertools.product(*(param_space[k] for k in keys)):
            params = dict(zip(keys, combo, strict=True))
            results.append((params, evaluate(params)))
        results.sort(key=lambda r: r[1], reverse=True)
        return results


class RandomSearch(SearchStrategy):
    """Samples `n_iter` random combinations instead of the full grid — useful when
    the grid is too large to exhaust."""

    def __init__(self, n_iter: int, seed: int | None = None) -> None:
        self.n_iter = n_iter
        self._rng = random.Random(seed)

    def search(self, param_space: ParamSpace, evaluate: Evaluate) -> list[tuple[ParamSet, float]]:
        keys = list(param_space)
        results: list[tuple[ParamSet, float]] = []
        for _ in range(self.n_iter):
            params = {k: self._rng.choice(param_space[k]) for k in keys}
            results.append((params, evaluate(params)))
        results.sort(key=lambda r: r[1], reverse=True)
        return results
