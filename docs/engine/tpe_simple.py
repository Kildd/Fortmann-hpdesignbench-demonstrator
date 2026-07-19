"""
Lightweight TPE sampler for integer catalog indices (no Optuna dependency).

Independent univariate Parzen estimators per dimension, following the
classic Bergstra et al. TPE idea used by Hyperopt/Optuna for discrete spaces.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field


@dataclass
class IntegerTPE:
    """Tree-structured Parzen Estimator over integer boxes [lb, ub]."""

    bounds: list[tuple[int, int]]
    seed: int = 42
    n_startup: int = 10
    gamma: float = 0.25
    n_candidates: int = 24
    _rng: random.Random = field(init=False, repr=False)
    _X: list[list[int]] = field(default_factory=list, init=False, repr=False)
    _Y: list[float] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)
        if not (0.0 < self.gamma < 1.0):
            raise ValueError("gamma must be in (0, 1)")

    @property
    def n_dims(self) -> int:
        return len(self.bounds)

    def tell(self, x: list[int], y: float) -> None:
        if len(x) != self.n_dims:
            raise ValueError(f"expected {self.n_dims} dims, got {len(x)}")
        self._X.append([int(v) for v in x])
        self._Y.append(float(y))

    def ask(self) -> list[int]:
        if len(self._X) < self.n_startup:
            return self._sample_uniform()

        # Lower y is better → "good" = lowest gamma-fraction.
        order = sorted(range(len(self._Y)), key=lambda i: self._Y[i])
        n_good = max(1, int(math.ceil(self.gamma * len(order))))
        good_idx = set(order[:n_good])
        X_good = [self._X[i] for i in range(len(self._X)) if i in good_idx]
        X_bad = [self._X[i] for i in range(len(self._X)) if i not in good_idx]
        if not X_bad:
            X_bad = X_good

        best_x = self._sample_uniform()
        best_score = -float("inf")
        for _ in range(self.n_candidates):
            cand = self._sample_from_good(X_good)
            score = self._log_density_ratio(cand, X_good, X_bad)
            if score > best_score:
                best_score = score
                best_x = cand
        return best_x

    def _sample_uniform(self) -> list[int]:
        return [self._rng.randint(lo, hi) for lo, hi in self.bounds]

    def _sample_from_good(self, X_good: list[list[int]]) -> list[int]:
        # Mix KDE-like sampling from observed good points with exploration.
        if self._rng.random() < 0.15 or not X_good:
            return self._sample_uniform()
        base = self._rng.choice(X_good)
        out: list[int] = []
        for d, (lo, hi) in enumerate(self.bounds):
            # Local integer perturbation around a good observation.
            span = max(1, (hi - lo) // 6)
            val = base[d] + self._rng.randint(-span, span)
            out.append(max(lo, min(hi, val)))
        return out

    def _log_density_ratio(
        self,
        x: list[int],
        X_good: list[list[int]],
        X_bad: list[list[int]],
    ) -> float:
        score = 0.0
        for d, (lo, hi) in enumerate(self.bounds):
            score += math.log(
                self._categorical_density(x[d], [row[d] for row in X_good], lo, hi)
                + 1e-12
            )
            score -= math.log(
                self._categorical_density(x[d], [row[d] for row in X_bad], lo, hi)
                + 1e-12
            )
        return score

    def _categorical_density(
        self,
        value: int,
        samples: list[int],
        lo: int,
        hi: int,
    ) -> float:
        # Laplace-smoothed histogram over the integer domain.
        width = hi - lo + 1
        counts = [1.0] * width  # prior
        for s in samples:
            if lo <= s <= hi:
                counts[s - lo] += 1.0
        total = sum(counts)
        return counts[value - lo] / total
