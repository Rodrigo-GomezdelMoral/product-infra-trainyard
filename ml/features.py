"""One feature row per unit from a 7-day telemetry window: the same function for training and for scoring."""

import pandas as pd

ANALOGUE = ("TP2", "TP3", "H1", "DV_pressure", "Reservoirs", "Oil_temperature", "Motor_current")
DIGITAL = ("COMP", "DV_electric", "Towers", "MPG", "LPS", "Oil_level")
SLOTS_PER_DAY = 144
WINDOW = HORIZON = pd.Timedelta(days=7)
RECENT = pd.Timedelta(days=2)
PARKED = (pd.Timedelta(minutes=30), pd.Timedelta(hours=5, minutes=30))
FEATURES = (
    "series_b",
    "observed_days",
    "duty_parked",
    "duty_service",
    "duty_trend",
    "below_cut_in",
    "below_7_bar",
    "reservoir_bar",
    "oil_temperature",
    "oil_temperature_max",
    "motor_current",
)
LABEL = "failure_7d"


def features(telemetry: pd.DataFrame, failures: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    repaired = failures.loc[failures["failed_at"] < as_of].groupby("unit")["failed_at"].max()
    window = telemetry.loc[telemetry["timestamp"].between(as_of - WINDOW, as_of, inclusive="left")]
    since = window["unit"].map(repaired)
    window = window.loc[since.isna() | (window["timestamp"] > since)]
    clock = window["timestamp"] - window["timestamp"].dt.normalize()
    parked = clock.between(*PARKED, inclusive="left")
    service = window["DV_electric"].where(~parked)
    recent = service.where(window["timestamp"] >= as_of - RECENT)
    grouped = window.assign(parked=window["DV_electric"].where(parked), service=service, recent=recent).groupby("unit")
    rows = pd.DataFrame(
        {
            "series_b": grouped["series"].first().eq("B").astype(int),
            "observed_days": grouped.size() / SLOTS_PER_DAY,
            "duty_parked": grouped["parked"].mean(),
            "duty_service": grouped["service"].mean(),
            "duty_trend": grouped["recent"].mean() - grouped["service"].mean(),
            "below_cut_in": grouped["MPG"].mean(),
            "below_7_bar": grouped["LPS"].mean(),
            "reservoir_bar": grouped["Reservoirs"].mean(),
            "oil_temperature": grouped["Oil_temperature"].mean(),
            "oil_temperature_max": grouped["Oil_temperature"].max(),
            "motor_current": grouped["Motor_current"].mean(),
        }
    )
    return rows.round(4).reset_index().assign(as_of=as_of)[["unit", "as_of", *FEATURES]]


def training_rows(telemetry: pd.DataFrame, failures: pd.DataFrame) -> pd.DataFrame:
    end = telemetry["timestamp"].max().normalize() + pd.Timedelta(days=1)
    dates = pd.date_range(telemetry["timestamp"].min().normalize() + WINDOW, end - HORIZON, freq="D")
    rows = pd.concat([features(telemetry, failures, as_of) for as_of in dates], ignore_index=True)
    upcoming = failures.sort_values("failed_at")
    rows = pd.merge_asof(rows, upcoming, left_on="as_of", right_on="failed_at", by="unit", direction="forward")
    return rows.assign(**{LABEL: (rows["failed_at"] < rows["as_of"] + HORIZON).astype(int)}).drop(columns="failed_at")
