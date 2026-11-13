"""Evaluation integrity: walk-forward predictions never use later prices, the extra baselines are reported without
changing any existing number, and the live scorecard and model report describe themselves accurately."""
import numpy as np
import pytest

from app import config
from app.forecast import FEATURES, fold_schedule, forecast, make_features, walk_forward
from app.main import report_method
from app.models import MODELS, build_context
from app.trackrecord import INTERVAL_METHOD, scorecard

from .conftest import synthetic_prices


def _perturb_after(close, cutoff_pos: int, factor: float = 1.3):
    """Same dates and length, but every price after ``cutoff_pos`` is changed (a different 'future')."""
    changed = close.copy()
    changed.iloc[cutoff_pos + 1:] *= factor
    changed.iloc[cutoff_pos + 1:] *= np.linspace(1.0, 0.7, len(changed) - cutoff_pos - 1)
    return changed


def _test_rows(folds):
    return np.concatenate([np.arange(t.start, t.stop) for _, t in folds])


@pytest.mark.parametrize("horizon", [5, 20])
def test_point_model_predictions_do_not_depend_on_later_prices(horizon):
    """Leakage regression test. For every fold, change every price after the fold's first test date; each model's
    walk-forward prediction for any test date on or before that date must be exactly the same. Putting the cutoff at
    the start of each test block is what makes this strict: a missing or short embargo (a training label reaching into
    the test block), look-ahead in a feature, or scaling fitted on later data would all change the first prediction."""
    close = synthetic_prices(900, seed=7)["Close"]
    a = build_context(close, horizon)
    folds = fold_schedule(len(a.X), horizon)
    rows = _test_rows(folds)
    for _, block in folds:
        cutoff_date = a.X.index[block.start]
        b = build_context(_perturb_after(close, close.index.get_loc(cutoff_date)), horizon)
        assert a.X.index.equals(b.X.index)
        before = a.X.index[rows] <= cutoff_date
        for model in MODELS:
            pa = np.concatenate([model.predict(a, te, t) for te, t in folds])
            pb = np.concatenate([model.predict(b, te, t) for te, t in folds])
            np.testing.assert_allclose(pa[before], pb[before], rtol=0, atol=1e-12,
                                       err_msg=f"{model.name}: prediction changed when only later prices changed")


def test_forecast_walk_forward_does_not_depend_on_later_prices():
    """The same check for the main forecast's walk-forward (the predictions behind its skill, verdict and bands)."""
    close = synthetic_prices(900, seed=8)["Close"]
    h = 10

    def wf(c):
        logp = np.log(c)
        data = make_features(c).assign(target=logp.shift(-h) - logp).dropna()
        return data.index, walk_forward(data[FEATURES], data["target"], h)

    idx, wa = wf(close)
    folds = fold_schedule(len(idx), h)
    rows = _test_rows(folds)
    for _, block in folds:
        cutoff_date = idx[block.start]
        _, wb = wf(_perturb_after(close, close.index.get_loc(cutoff_date)))
        before = idx[rows] <= cutoff_date
        np.testing.assert_allclose(wa.y_pred[before], wb.y_pred[before], rtol=0, atol=1e-12)


def test_drift_baseline_is_reported_and_existing_numbers_are_unchanged():
    close = synthetic_prices(900, seed=2)["Close"]
    bt = forecast(close, 5)["backtest"]
    d = bt["drift_baseline"]
    assert d["rmse"] > 0 and d["mae"] > 0 and 0 <= d["directional_accuracy"] <= 1
    assert bt["skill_vs_drift"] == pytest.approx(1 - bt["model"]["rmse"] / d["rmse"])
    assert d["skill_vs_naive"] == pytest.approx(1 - d["rmse"] / bt["naive_baseline"]["rmse"])
    # the verdict and the headline skill are still judged against "flat" only
    assert bt["skill_vs_baseline"] == pytest.approx(1 - bt["model"]["rmse"] / bt["naive_baseline"]["rmse"])
    assert bt["n_folds"] == len(fold_schedule(len(make_features(close).dropna()) - 5, 5))
    assert f"{bt['n_folds']} folds" in bt["method"]


def test_drift_baseline_matches_the_model_comparison():
    """Same rows, same rule: the forecast's drift baseline equals the 'drift' row of the model comparison."""
    from app.models import compare_models
    close = synthetic_prices(900, seed=4)["Close"]
    bt = forecast(close, 5)["backtest"]
    drift = next(m for m in compare_models(close, 5)["models"] if m["model"] == "drift")
    assert bt["drift_baseline"]["rmse"] == pytest.approx(drift["rmse"])
    assert bt["drift_baseline"]["skill_vs_naive"] == pytest.approx(drift["skill_vs_naive"])


def test_report_method_uses_the_real_fold_count():
    method = report_method([{"n_folds": 7}, {"n_folds": 7}], 5)
    assert method.startswith("Expanding-window walk-forward, 7 folds, 5-day")
    assert "6/7 folds" in report_method([{"n_folds": 7}, {"n_folds": 6}], 5)
    assert "several folds" in report_method([{}], 5)  # rows cached by an older build


def test_model_report_rows_carry_drift_and_folds(client, monkeypatch):
    monkeypatch.setattr(config, "REPORT_SYMBOLS", ["SPY"])
    body = client.get("/api/model-report").json()
    row = body["rows"][0]
    assert row["drift_rmse"] > 0 and isinstance(row["skill_vs_drift"], float)
    assert f"walk-forward, {row['n_folds']} folds," in body["method"]


def _resolved(i, real, low=95.0, high=106.0, date=None):
    return {"status": "resolved", "horizon_days": 5, "base_date": date or f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}",
            "predicted_return": 0.0, "realized_return": real, "base_close": 100.0, "interval_low": low,
            "interval_high": high, "symbol": "SPY"}


def test_scorecard_coverage_has_a_plausible_range_based_on_independent_periods():
    few = scorecard([_resolved(i, 0.0) for i in range(10)])  # 10 dates, 5-day horizon: ~2 independent periods
    lo, hi = few["interval_coverage_ci_90"]
    assert few["interval_coverage"] == 1.0 and few["n_independent"] == 2
    assert lo < 0.6 and hi == 1.0  # 100% from two periods is not evidence of anything
    rng = np.random.default_rng(0)
    many = scorecard([_resolved(i, float(r)) for i, r in enumerate(rng.normal(0, 0.03, 400))])
    mlo, mhi = many["interval_coverage_ci_90"]
    assert mlo <= many["interval_coverage"] <= mhi and (mhi - mlo) < (hi - lo)
    assert many["interval_method"] == INTERVAL_METHOD and "not the conformal" in INTERVAL_METHOD
