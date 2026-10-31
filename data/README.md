# Fleet feed

> **Synthetic data.** Every value in Trainyard's fleet feed comes from the seeded process below, in `app/domain/simulator.py`. The signal names, units and meanings follow the public **MetroPT-3** dataset, which serves as the schema reference only: N. Davari, B. Veloso, R. Ribeiro and J. Gama, *MetroPT-3 Dataset*, UCI Machine Learning Repository, [doi:10.24432/C5VW3R](https://doi.org/10.24432/C5VW3R), CC BY 4.0. MetroPT-3's data is not used: it records one train, four air-leak failures and February to August 2020, which cannot show a ranked fleet, two series, retraining cycles or a controlled drift (ADR-012).

## What the feed contains

Two tables, both in UTC.

**Telemetry**: one row per unit and 10-minute slot, 5,760 rows a day for the 40 units, about 2.1 million rows and 254 MB in memory a year. Analogue signals are the slot's mean; digital signals are the share of the slot during which they were active.

| Column | Unit | MetroPT-3 meaning | How the simulator produces it |
|---|---|---|---|
| `timestamp`, `unit`, `series` | | | slot start; EMU 2401 to 2440; `A` (2401–2420, older) or `B` (2421–2440, newer) |
| `TP2` | bar | pressure on the compressor | proportional to the duty cycle, up to 0.4 bar below cut-out |
| `TP3` | bar | pressure at the pneumatic panel | midpoint of cut-in and cut-out plus 0.15 bar, minus 0.9 bar × severity |
| `H1` | bar | pressure drop when the cyclonic separator filter discharges | high while the compressor is off: (1 − duty) × (TP3 − 0.4) |
| `DV_pressure` | bar | pressure drop when the tower air dryers discharge; zero under load | 0.6 × duty × (1 − duty) |
| `Reservoirs` | bar | downstream reservoir pressure, close to TP3 | TP3 − 0.03 |
| `Oil_temperature` | °C | compressor oil temperature | 48 + 32 × duty |
| `Motor_current` | A | one phase of the motor: about 0 off, 4 offloaded, 7 under load | 7 × duty, plus 4 A for up to 10 % of the slot running offloaded in service |
| `COMP` | share | air intake valve: active when off or offloaded | 1 − duty |
| `DV_electric` | share | compressor outlet valve: active under load | the duty cycle |
| `Towers` | share | which drying tower works | about 0.5: the towers alternate; carries no signal |
| `MPG` | share | starts the compressor when pressure falls below 8.2 bar | 0.02 + 0.03 × duty + 0.22 × severity |
| `LPS` | share | pressure below 7 bar | 0.12 × severity², zero when healthy |
| `Oil_level` | share | oil below the expected level | random flicker in 1 % of slots; carries no signal |

Every signal also carries Gaussian noise per slot, and values are rounded to three decimals.

**Failures**: the work-order log, one row per in-service APU failure with `unit` and `failed_at`. It holds only failures that have already happened by the end of the feed.

## The process

**Timetable.** Every unit is parked from 00:30 to 05:30, with morning (07:00–09:30) and evening (17:00–19:30) peaks. While parked nothing consumes air, so the compressor runs only to make up leaks: the parked duty cycle is the clearest leak signal.

**Healthy duty cycle.** In service 0.24 of the time, plus 0.08 in the peaks; a base leak and wear add 0.08 for Series A and 0.04 for Series B, parked or not. Each unit has its own fixed offsets: duty cycle (standard deviation 0.015), oil temperature (1.5 °C) and pressure (0.05 bar).

**Failures.** Each unit fails on a given day with probability 0.58 % in Series A and 0.25 % in Series B, which gives about 5 failures a month across the fleet, the customer's figure, with Series B failing less. A failure happens at a random slot between 06:00 and midnight, in service.

**Degradation before every failure.** An air leak and valve wear build up over a lead time drawn between 6 and 12 days. Severity grows from 0 to 1 as `((t − (failure − lead)) / lead)²`, slowly at first and fast at the end, and it:
- adds 0.30 × severity to the duty cycle, parked and in service, which raises motor current, compressor pressure and oil temperature with it;
- lowers the panel and reservoir pressure by up to 0.9 bar, because pressure recovers more slowly;
- adds up to 0.22 to the share of time below 8.2 bar and up to 0.12 to the share below 7 bar.

**After a failure** the unit is out of service, with no telemetry, until midnight. It is repaired overnight and returns healthy the next day.

**Scenario `firmware-b`.** From a given date, a firmware update moves Series B's governor from 8.2 and 10.0 bar to 8.6 and 10.4 bar. Series B's mean pressures rise by 0.4 bar and its duty cycle by 12 %. Pressure now rarely falls below the 8.2-bar switch, so the share of time below 8.2 bar falls to 40 % of its level, and the leak signature on that switch and on the 7-bar switch weakens. Series A is unchanged, and the data before the date is identical to the feed without the scenario. This is the drift the monitor has to catch.

**Determinism.** Each day is drawn from its own random streams, keyed by the seed and the date: the failure draws, the lead times and the noise. Generating 20 days at once or 10 and then 10 gives the same feed row for row, so advancing the feed by a few days never rewrites history. A failure scheduled after the end of the feed already shapes the degradation of the last days, as in a real fleet, but it appears in the failure log only once it has happened. The default seed is 42: its failure counts match the customer's rate over the windows checked (35 A and 16 B in the year from 2025-11-01, 38 and 17 in 2026, 45 and 18 in the year from 2026-06-01).

## Labels and features

`ml/features.py` turns a feed into model rows. Training (the `prep` step) and scoring (the app) call the same function, `features`, and `tests/test_features.py` proves they give identical rows.

- **As of** a midnight, one row per unit from the 7 days before it. The window restarts after the unit's last repair, so a repaired compressor is not judged on the leak that broke it; `observed_days` says how much of the window there is. A unit with no telemetry since its repair has no row.
- **Label** `failure_7d`: 1 when the unit fails within the 7 days from the as-of midnight. A label is known 7 days later, so training rows stop 7 days before the end of the feed.

| Feature | Definition |
|---|---|
| `series_b` | 1 for Series B |
| `observed_days` | days of telemetry in the window since the last repair, at most 7 |
| `duty_parked` | mean `DV_electric` while parked |
| `duty_service` | mean `DV_electric` in service |
| `duty_trend` | mean `DV_electric` in service over the last 2 days, minus the window's |
| `below_cut_in` | mean `MPG`: share of time below 8.2 bar |
| `below_7_bar` | mean `LPS`: share of time below 7 bar |
| `reservoir_bar` | mean `Reservoirs` |
| `oil_temperature`, `oil_temperature_max` | mean and highest 10-minute `Oil_temperature` |
| `motor_current` | mean `Motor_current` |

Over the 2026 feed with the default seed, 2.6 % of the 14,026 training rows are positive. The median healthy row has a parked duty cycle of 0.054 and spends 2.8 % of the time below 8.2 bar; the median row in the week before a failure has 0.101 and 5.0 %.

## What the simulator does not model

- **Failures without warning.** Every failure has a precursor of 6 to 12 days, so a model trained on this feed looks better than it would on a real fleet.
- **Other failure modes:** oil leaks, motor or electrical faults, and sensor faults. `Oil_level` and `Towers` carry no signal.
- **Interventions.** The feed does not react to Trainyard's recommendations: an inspected unit still fails on schedule.
- **Seasons, weekends and timetable changes,** ambient temperature, and unit ageing.
- **Repairs that take longer than the rest of the failure day,** and the short gap real units need before failing again.
- **Calibration.** Levels are physically plausible, not fitted to MetroPT-3's recordings.

## How the feed is produced

`simulate(start, days, seed, firmware_b_from)` returns the telemetry and the failure log for whole days from `start`. Seeding the feed, advancing it and switching the `firmware-b` scenario on are delivery-workflow inputs, never runs from a laptop (ADR-012), so each environment's feed is produced by its own identity and logged in the Actions history.
