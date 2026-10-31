# ADR-012 · A synthetic fleet feed in the MetroPT-3 schema, operated through the delivery workflows

**Status:** accepted · **Date:** 2026-10-30

## Context

Trainyard needs fleet telemetry with labelled failures to train, compare, monitor and retrain a model, and to show it working end to end. The customer's data is not available and real customer data is out of scope. The closest public dataset, MetroPT-3, has the right signals but records one train, four air-leak failures and February to August 2020: it cannot produce a ranked fleet of 40 units, two series with different failure rates, several retraining cycles or a drift that appears on a chosen date.

## Options

1. **Replay MetroPT-3 across 40 units**, shifted in time. The same four failures would appear 40 times, a time-based split would leak them between training and holdout, and there would be no controlled drift.
2. **A generative model trained on MetroPT-3** (CTGAN, TimeGAN). It would learn one train's normal behaviour but not labelled precursors to failure, it could not create a drift on demand, and it adds a heavy dependency that has to be trained before anything else runs.
3. **A documented, seeded process model in the MetroPT-3 schema.** Every signal is a formula of the duty cycle, the pressure and a degradation severity that rises before each failure, plus noise. Its parameters fit on one page.

## Decision

**Option 3.** `app/domain/simulator.py` generates 10-minute aggregates of the MetroPT-3 analogue and digital signals, with the names and units of the dataset, for EMU 2401 to 2440. `data/README.md` documents every formula, every parameter and what the process does not model.

- **One random stream per day,** keyed by the seed and the date. Any range of days is the same whether it is generated at once or day by day, so the feed advances without rewriting history, and the same inputs and seed always give the same data (REQ-02).
- **A precursor before every failure,** 6 to 12 days of rising leak and valve wear, so that the label "fails within 7 days" is learnable and the phase 3 gate is reachable.
- **Series B fails less** (0.25 % a unit-day against 0.58 %), about 5 failures a month in total, the customer's figure.
- **The `firmware-b` scenario** moves Series B's governor pressures from a date, a drift in the inputs that the monitor must flag (REQ-04).
- **Feed operations go through the delivery workflows:** seeding, advancing days and switching `firmware-b` on are `workflow_dispatch` inputs of `deploy.yml` and `release.yml`, never runs from a laptop. Each environment's feed is produced by its own identity and logged in the Actions history.

## State

- Implemented and tested in phase 1: the simulator, the feature and label functions, the reproducibility, parity and degradation tests.
- Implemented in phase 7: the `feed_days` and `firmware_b_from` inputs of `deploy.yml` and `release.yml`, which register a new `fleet-feed` version through `.github/actions/ship`.
- Pending: the first feed as a data asset in staging (phase 8).

## Consequences

- Every failure has a warning, so measured recall and precision are better than a real fleet would allow. `data/README.md` says so now; the model card and `RESPONSIBLE_AI.md` (phase 4) and the README (phase 9) must say it too.
- The feed's realism is plausibility, not calibration: levels are not fitted to MetroPT-3's recordings.
- A year of telemetry is about 2.1 million rows and 254 MB in memory, and building its training rows took 15 seconds on a laptop. `prep` fits on one `Standard_F2s_v2` node (4 GiB). Measured in phase 3, in the Azure Machine Learning environment under a hard 4 GiB limit: a year of feed peaked at 952 MiB and took 14 s.
- MetroPT-3 is cited as the schema reference under CC BY 4.0; none of its data is copied.
