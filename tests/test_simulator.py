from datetime import timedelta

import pandas as pd
from pandas.testing import assert_frame_equal

from app.domain.simulator import Feed, simulate
from ml.features import ANALOGUE, DIGITAL
from tests.conftest import START


def test_simulation_is_reproducible_and_advances_day_by_day() -> None:
    whole, again = simulate(START, 20), simulate(START, 20)
    first, rest = simulate(START, 10), simulate(START + timedelta(days=10), 10)
    for part in range(2):
        assert_frame_equal(whole[part], again[part])
        assert_frame_equal(whole[part], pd.concat([first[part], rest[part]], ignore_index=True))
    assert len(whole.failures) == 3
    assert not whole.telemetry.equals(simulate(START, 20, seed=7).telemetry)
    assert list(whole.telemetry.columns) == ["timestamp", "unit", "series", *ANALOGUE, *DIGITAL]


def test_failures_are_preceded_by_degradation(feed: Feed, rows: pd.DataFrame) -> None:
    signals = ["duty_parked", "below_cut_in"]
    before = rows.merge(feed.failures.assign(as_of=feed.failures["failed_at"].dt.normalize()), on=["unit", "as_of"])
    rise = before[signals] - rows.groupby("unit")[signals].median().loc[before["unit"]].to_numpy()
    assert len(before) == 15
    assert rise["duty_parked"].min() > 0.05 and rise["below_cut_in"].min() > 0.04
    assert (feed.failures["unit"] < 2421).sum() > (feed.failures["unit"] >= 2421).sum()


def test_firmware_b_shifts_series_b_from_its_date() -> None:
    switch = START + timedelta(days=5)
    base, firmware = simulate(START, 10).telemetry, simulate(START, 10, firmware_b_from=switch).telemetry
    before = base["timestamp"] < pd.Timestamp(switch)
    assert_frame_equal(base[before], firmware[before])
    signals = ["Reservoirs", "DV_electric", "MPG"]
    shift = (firmware[~before].groupby("series", observed=True)[signals].mean()) - (
        base[~before].groupby("series", observed=True)[signals].mean()
    )
    series_b = shift.loc["B"]
    assert (shift.loc["A"] == 0).all()
    assert abs(series_b["Reservoirs"] - 0.4) < 0.01 and series_b["DV_electric"] > 0.01 and series_b["MPG"] < -0.01
