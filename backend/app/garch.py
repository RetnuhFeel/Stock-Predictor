"""GJR-GARCH(1,1) volatility model, implemented here instead of pulling in the ``arch`` package.

Why not ``arch``: it needs statsmodels (plus patsy) on top of scipy, which is a big install and import-time/memory
cost on Render's free 512 MB instance, for one model. GJR-GARCH(1,1) is a short, well-known recursion, so it lives here
(about 100 lines, unit-tested, and cross-checked against ``arch`` in a scratch environment while developing).

Model (returns r_t in percent, mean assumed zero):
    s2_t = omega + (alpha + gamma * 1[r_{t-1} < 0]) * r_{t-1}^2 + beta * s2_{t-1}
GJR adds ``gamma``: a down day raises tomorrow's variance more than an up day of the same size (the leverage effect).
Estimation: Gaussian quasi-maximum-likelihood with variance targeting (omega is set so the long-run variance equals the
sample variance), so only (alpha, gamma, beta) are fitted. Constraints: all >= 0 and alpha + gamma/2 + beta < 1.

The recursion is linear in s2, so a whole path is one ``scipy.signal.lfilter`` call (no Python loop): fast enough to
refit in every walk-forward fold. A hard time budget (``deadline_s``) stops a runaway fit.

h-step forecast: with p = alpha + gamma/2 + beta and V = long-run variance,
    E[s2_{t+k}] = V + p^(k-1) * (s2_{t+1} - V)
and the forecast of realised volatility over the next h days (the quantity the volatility panel judges) is
    sqrt( mean over k = 1..h of E[s2_{t+k}] ).
Unlike EWMA (a flat forecast), this reverts toward the long-run level, which matters at long horizons.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize
from scipy.signal import lfilter

MIN_OBS = 250
P_MAX = 0.9995  # persistence ceiling: keeps the long-run variance finite and the forecast well defined
STARTS = ((0.04, 0.08, 0.88), (0.10, 0.10, 0.70))


class GarchUnavailable(Exception):
    """The fit failed, did not converge sanely, or ran out of its time budget."""


@dataclass(frozen=True)
class GjrFit:
    alpha: float
    gamma: float
    beta: float
    omega: float          # percent^2
    long_run_var: float   # percent^2 per day (= the sample variance, by variance targeting)
    loglik: float
    converged: bool

    @property
    def persistence(self) -> float:
        return self.alpha + self.gamma / 2 + self.beta

    @property
    def half_life_days(self) -> float | None:
        p = self.persistence
        return float(np.log(0.5) / np.log(p)) if 0 < p < 1 else None

    @property
    def long_run_annual_vol(self) -> float:
        return float(np.sqrt(self.long_run_var) / 100 * np.sqrt(252))


def next_variance(r: np.ndarray, alpha: float, gamma: float, beta: float, omega: float, s0: float) -> np.ndarray:
    """s2_{t+1|t} for every t: the one-step-ahead variance given returns up to and including r[t]."""
    u = omega + (alpha + gamma * (r < 0)) * r * r
    return lfilter([1.0], [1.0, -beta], u, zi=[beta * s0])[0]


def _neg_loglik(theta: np.ndarray, r: np.ndarray, v: float) -> float:
    alpha, gamma, beta = theta
    p = alpha + gamma / 2 + beta
    if p >= P_MAX or min(theta) < 0:
        return 1e10
    nxt = next_variance(r, alpha, gamma, beta, v * (1 - p), v)
    s2 = np.concatenate(([v], nxt[:-1]))  # variance used for r[t] is the one-step forecast made at t-1
    if not np.all(np.isfinite(s2)) or s2.min() <= 0:
        return 1e10
    return float(0.5 * np.sum(np.log(s2) + r * r / s2))


def fit_gjr(returns_pct: np.ndarray, deadline_s: float | None = None) -> GjrFit:
    """Fit GJR-GARCH(1,1) to daily percent log returns. Raises GarchUnavailable if it cannot be done sensibly."""
    r = np.asarray(returns_pct, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) < MIN_OBS:
        raise GarchUnavailable(f"need at least {MIN_OBS} daily returns, got {len(r)}")
    v = float(np.mean(r * r))
    if v <= 1e-12:
        raise GarchUnavailable("returns have no variation")
    t_end = None if deadline_s is None else time.monotonic() + deadline_s

    def obj(theta):
        if t_end is not None and time.monotonic() > t_end:
            raise GarchUnavailable("fit exceeded its time budget")
        return _neg_loglik(theta, r, v)

    best = None
    cons = [{"type": "ineq", "fun": lambda x: P_MAX - (x[0] + x[1] / 2 + x[2])}]
    for x0 in STARTS:
        res = minimize(obj, x0, method="SLSQP", bounds=[(0, 1)] * 3, constraints=cons,
                       options={"maxiter": 200, "ftol": 1e-9})
        if np.isfinite(res.fun) and res.fun < 1e9 and (best is None or res.fun < best.fun):
            best = res
    if best is None:
        raise GarchUnavailable("the optimiser found no valid parameters")
    alpha, gamma, beta = (float(x) for x in best.x)
    p = alpha + gamma / 2 + beta
    return GjrFit(alpha, gamma, beta, v * (1 - p), v, -best.fun - 0.5 * len(r) * np.log(2 * np.pi), bool(best.success))


def horizon_vol(fit: GjrFit, r: np.ndarray, horizon: int, s0: float | None = None) -> np.ndarray:
    """Forecast daily volatility (decimal, i.e. NOT percent) over the next ``horizon`` days at every origin in ``r``.

    ``r`` are daily percent log returns, oldest first; the result has the same length (element t uses r[:t+1] only)."""
    s0 = fit.long_run_var if s0 is None else s0
    nxt = next_variance(np.asarray(r, dtype=float), fit.alpha, fit.gamma, fit.beta, fit.omega, s0)
    p, v = fit.persistence, fit.long_run_var
    if abs(1 - p) < 1e-9:
        mean_var = nxt
    else:
        mean_var = v + (nxt - v) * (1 - p**horizon) / (horizon * (1 - p))
    return np.sqrt(np.maximum(mean_var, 1e-12)) / 100.0
