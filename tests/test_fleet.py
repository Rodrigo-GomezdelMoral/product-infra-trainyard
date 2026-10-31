import pandas as pd

from app.domain.fleet import SIGNALS, plan
from app.domain.simulator import Feed
from ml.features import FEATURES, features


def week(feed: Feed, flagged: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = features(feed.telemetry, feed.failures, pd.Timestamp("2026-02-10"))
    probability = [0.95, 0.9, 0.9, 0.8, 0.7, 0.66, 0.61, 0.6, 0.55][:flagged] + [0.1] * (len(rows) - flagged)
    scores = pd.DataFrame(0.0, index=rows.index, columns=list(FEATURES)).assign(
        unit=rows["unit"].to_numpy()[::-1], probability=probability
    )
    return rows, scores


def test_fleet_risk_budget(feed: Feed) -> None:
    rows, scores = week(feed, 9)
    inspection = plan(rows, scores, threshold=0.5)
    probabilities = [unit.probability for unit in inspection.units]
    assert len(inspection.units) == 6 and probabilities == sorted(probabilities, reverse=True)
    assert [unit.unit for unit in inspection.units[1:3]] == ["EMU 2438", "EMU 2439"]
    assert inspection.over_budget == ("EMU 2434", "EMU 2433", "EMU 2432")
    assert min(probabilities) >= 0.5 and {unit.series for unit in inspection.units} == {"B"}
    assert len(plan(*week(feed, 2), threshold=0.5).units) == 2


def test_explanations_quote_this_weeks_values(feed: Feed) -> None:
    rows, scores = week(feed, 1)
    pushed = {"series_b": 2.0, "duty_parked": 0.9, "below_cut_in": 0.5, "duty_trend": 0.1, "oil_temperature": -0.3}
    scores.loc[0, list(pushed)] = list(pushed.values())
    unit = scores.at[0, "unit"]
    value, median = rows.set_index("unit").at[unit, "duty_parked"], rows["duty_parked"].median()
    signals = plan(rows, scores, threshold=0.5).units[0].signals
    expected = [SIGNALS[name][0] for name in ("duty_parked", "below_cut_in", "duty_trend")]
    assert all(signal.startswith(label) for signal, label in zip(signals, expected, strict=True))
    assert signals[0] == f"compressor duty while parked {value:.0%}, fleet median {median:.0%}"
    assert set(SIGNALS) < set(FEATURES)
