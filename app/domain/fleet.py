"""REQ-06: this week's inspection list within the inspection budget, and each unit's top signals in plain words."""

from dataclasses import dataclass

import pandas as pd

INSPECTION_BUDGET = 6
SIGNALS = {
    "duty_parked": ("compressor duty while parked", "{:.0%}"),
    "duty_service": ("compressor duty in service", "{:.0%}"),
    "duty_trend": ("change in duty over the last 2 days", "{:+.1%}"),
    "below_cut_in": ("time below 8.2 bar", "{:.1%}"),
    "below_7_bar": ("time below 7 bar", "{:.2%}"),
    "reservoir_bar": ("mean reservoir pressure", "{:.2f} bar"),
    "oil_temperature": ("mean oil temperature", "{:.1f} °C"),
    "oil_temperature_max": ("peak oil temperature", "{:.1f} °C"),
    "motor_current": ("mean motor current", "{:.2f} A"),
}


@dataclass(frozen=True)
class UnitRisk:
    unit: str
    series: str
    probability: float
    signals: tuple[str, ...]


@dataclass(frozen=True)
class Inspection:
    units: tuple[UnitRisk, ...]
    over_budget: tuple[str, ...]


def explain(rows: pd.DataFrame, scores: pd.DataFrame, unit: int) -> tuple[str, ...]:
    values = rows.set_index("unit")[list(SIGNALS)]
    pushed = scores.loc[scores["unit"] == unit, list(SIGNALS)].iloc[0]
    top = pushed[pushed > 0].nlargest(3).index
    return tuple(
        f"{SIGNALS[s][0]} {SIGNALS[s][1].format(values.at[unit, s])}, "
        f"fleet median {SIGNALS[s][1].format(values[s].median())}"
        for s in top
    )


def plan(rows: pd.DataFrame, scores: pd.DataFrame, threshold: float, budget: int = INSPECTION_BUDGET) -> Inspection:
    flagged = scores.loc[scores["probability"] >= threshold].sort_values(
        ["probability", "unit"], ascending=[False, True]
    )
    series, top = rows.set_index("unit")["series_b"], flagged.iloc[:budget]
    units = tuple(
        UnitRisk(f"EMU {u}", "B" if series[u] else "A", round(p, 3), explain(rows, scores, u))
        for u, p in zip(top["unit"], top["probability"], strict=True)
    )
    return Inspection(units, tuple(f"EMU {u}" for u in flagged["unit"].iloc[budget:]))
