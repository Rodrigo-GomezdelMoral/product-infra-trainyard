import pandas as pd
from pandas.testing import assert_frame_equal

from app.domain.simulator import Feed
from ml.features import LABEL, WINDOW, features


def test_feature_parity(feed: Feed, rows: pd.DataFrame) -> None:
    telemetry, failures = feed
    for as_of in pd.to_datetime(["2026-01-08", "2026-01-15", "2026-02-10", "2026-03-25"]):
        week = telemetry.loc[telemetry["timestamp"].between(as_of - WINDOW, as_of, inclusive="left")]
        scored = features(week, failures.loc[failures["failed_at"] < as_of], as_of)
        trained = rows.loc[rows["as_of"] == as_of].drop(columns=LABEL).reset_index(drop=True)
        assert len(scored) >= 39
        assert_frame_equal(scored, trained)


def test_labels_mark_the_seven_days_before_each_failure(feed: Feed, rows: pd.DataFrame) -> None:
    days = pd.to_timedelta(range(7), unit="D")
    expected = {(u, at.normalize() - d) for u, at in feed.failures.itertuples(index=False, name=None) for d in days}
    keys = set(rows[["unit", "as_of"]].itertuples(index=False, name=None))
    assert set(rows.loc[rows[LABEL] == 1, ["unit", "as_of"]].itertuples(index=False, name=None)) == expected & keys
    assert rows["as_of"].max() == pd.Timestamp("2026-03-25")


def test_window_restarts_after_a_repair(feed: Feed, rows: pd.DataFrame) -> None:
    unit, failed_at = 2417, pd.Timestamp("2026-01-28 07:20")
    after = rows.loc[(rows["unit"] == unit) & (rows["as_of"] == failed_at.normalize() + pd.Timedelta(days=3))].iloc[0]
    usual = rows.loc[rows["unit"] == unit, "duty_parked"].median()
    assert after["observed_days"] == 2 and abs(after["duty_parked"] - usual) < 0.01
