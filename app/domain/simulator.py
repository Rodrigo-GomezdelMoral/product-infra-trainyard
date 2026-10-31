"""Synthetic fleet feed: 10-minute APU aggregates per unit in the MetroPT-3 signal schema, from a seeded process."""

from datetime import date
from typing import NamedTuple

import numpy as np
import pandas as pd

from ml.features import ANALOGUE, DIGITAL, PARKED, SLOTS_PER_DAY

UNITS = np.arange(2401, 2441)
SERIES_B = UNITS >= 2421
SEED = 42
SLOT = pd.Timedelta(minutes=10)
CLOCK = pd.timedelta_range(0, periods=SLOTS_PER_DAY, freq=SLOT)
DAILY_FAILURE_RATE = np.where(SERIES_B, 0.0025, 0.0058)
LEAD_DAYS = (6.0, 12.0)
CUT_IN, CUT_OUT, FIRMWARE_B_SHIFT = 8.2, 10.0, 0.4
NEVER = np.datetime64("2200-01-01", "ns")


def _within(*spans: tuple[pd.Timedelta, pd.Timedelta]) -> np.ndarray:
    return np.asarray(np.any([(start <= CLOCK) & (end > CLOCK) for start, end in spans], axis=0), dtype=bool)


PARKED_SLOTS = _within(PARKED)
PEAK_SLOTS = _within(
    (pd.Timedelta(hours=7), pd.Timedelta(hours=9.5)), (pd.Timedelta(hours=17), pd.Timedelta(hours=19.5))
)


class Feed(NamedTuple):
    telemetry: pd.DataFrame
    failures: pd.DataFrame


def simulate(start: date, days: int, seed: int = SEED, firmware_b_from: date | None = None) -> Feed:
    first = pd.Timestamp(start)
    ahead = days + int(LEAD_DAYS[1]) + 1
    schedule = pd.concat([_failures(first + pd.Timedelta(days=d), seed) for d in range(ahead)], ignore_index=True)
    mine = [schedule.loc[schedule["unit"] == unit] for unit in UNITS]
    failed = [np.append(m["failed_at"].to_numpy(dtype="datetime64[ns]"), NEVER) for m in mine]
    lead = [np.append(m["lead_days"].to_numpy(), 1.0) for m in mine]
    offsets = np.random.default_rng([seed, 0]).normal(0, (0.015, 1.5, 0.05), (len(UNITS), 3))
    firmware = pd.Timestamp(firmware_b_from) if firmware_b_from else pd.Timestamp.max
    days_ = [first + pd.Timedelta(days=d) for d in range(days)]
    telemetry = pd.concat([_day(day, failed, lead, offsets, seed, day >= firmware) for day in days_], ignore_index=True)
    failures = schedule.loc[schedule["failed_at"] < first + pd.Timedelta(days=days), ["unit", "failed_at"]]
    return Feed(telemetry, failures.reset_index(drop=True))


def _failures(day: pd.Timestamp, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng([seed, 1, day.toordinal()])
    fails = rng.random(len(UNITS)) < DAILY_FAILURE_RATE
    slot = rng.integers(36, SLOTS_PER_DAY, len(UNITS))
    lead = rng.uniform(*LEAD_DAYS, len(UNITS))
    return pd.DataFrame({"unit": UNITS[fails], "failed_at": day + SLOT * slot[fails], "lead_days": lead[fails]})


def _degradation(times: np.ndarray, failed: list[np.ndarray], lead: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    severity = np.zeros((len(times), len(UNITS)))
    down = np.zeros((len(times), len(UNITS)), dtype=bool)
    for i, (at, days) in enumerate(zip(failed, lead, strict=True)):
        upcoming = np.searchsorted(at, times)
        left = (at[upcoming] - times) / np.timedelta64(1, "D")
        severity[:, i] = np.clip(1 - left / days[upcoming], 0, 1) ** 2
        last = at[np.searchsorted(at, times, side="right") - 1]
        down[:, i] = (times >= last) & (times.astype("datetime64[D]") == last.astype("datetime64[D]"))
    return severity, down


def _day(
    day: pd.Timestamp, failed: list[np.ndarray], lead: list[np.ndarray], offsets: np.ndarray, seed: int, firmware: bool
) -> pd.DataFrame:
    times = (day + CLOCK).to_numpy(dtype="datetime64[ns]")
    severity, down = _degradation(times, failed, lead)
    z = np.random.default_rng([seed, 2, day.toordinal()]).standard_normal((12, SLOTS_PER_DAY, len(UNITS)))
    parked = PARKED_SLOTS[:, None]
    fw = SERIES_B & firmware
    shift = FIRMWARE_B_SHIFT * fw
    demand = np.where(parked, 0.0, 0.24 + 0.08 * PEAK_SLOTS[:, None]) + np.where(SERIES_B, 0.04, 0.08) + offsets[:, 0]
    duty = np.clip((demand + 0.3 * severity + 0.03 * z[0]) * (1 + 0.12 * fw), 0, 1)
    tp3 = (CUT_IN + CUT_OUT) / 2 + 0.15 + shift - 0.9 * severity + offsets[:, 2] + 0.05 * z[2]
    signals = {
        "TP2": np.maximum((CUT_OUT + shift - 0.4) * duty + 0.08 * z[1], 0),
        "TP3": tp3,
        "H1": np.maximum((1 - duty) * (tp3 - 0.4) + 0.1 * z[3], 0),
        "DV_pressure": np.maximum(0.6 * duty * (1 - duty) + 0.02 * z[4], 0),
        "Reservoirs": tp3 - 0.03 + 0.02 * z[5],
        "Oil_temperature": 48 + 32 * duty + offsets[:, 1] + 0.8 * z[6],
        "Motor_current": np.maximum(7 * duty + 4 * np.minimum(1 - duty, 0.1) * ~parked + 0.1 * z[7], 0),
        "COMP": 1 - duty,
        "DV_electric": duty,
        "Towers": np.clip(0.5 + 0.06 * z[8], 0, 1),
        "MPG": np.clip((0.02 + 0.03 * duty + 0.22 * severity) * (1 - 0.6 * fw) + 0.01 * z[9], 0, 1),
        "LPS": np.clip(0.12 * severity**2 * (1 - 0.5 * fw) + 0.003 * z[10], 0, 1),
        "Oil_level": 0.1 * (z[11] < -2.33),
    }
    frame = pd.DataFrame(
        {
            "timestamp": np.repeat(times, len(UNITS)),
            "unit": np.tile(UNITS, SLOTS_PER_DAY),
            "series": pd.Categorical(np.tile(np.where(SERIES_B, "B", "A"), SLOTS_PER_DAY), categories=["A", "B"]),
            **{name: signals[name].ravel().round(3) for name in (*ANALOGUE, *DIGITAL)},
        }
    )
    return frame.loc[~down.ravel()]
