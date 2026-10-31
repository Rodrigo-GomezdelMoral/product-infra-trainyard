# ADR-013 · Rejections: streaming ingestion, feature store, sweeps, AutoML

**Status:** accepted · **Date:** 2026-10-31

## Context

Each of these is a common part of an MLOps platform. Trainyard leaves them out, because none of them changes this product's decision: which trains to inspect this week. Each would add cost, code or a second source of truth.

## Decisions

| Rejected | Why | What Trainyard does instead | Reconsider when |
|---|---|---|---|
| **Streaming ingestion** (Event Hubs, Stream Analytics) | The decision is weekly and the signals are 10-minute aggregates. A stream would bill while idle and end in the same weekly list. | The feed lands as a versioned `fleet-feed` data asset through the delivery workflows (ADR-012). | the operator wants alerts within the hour, not inspections within the week |
| **A feature store** (Azure ML managed feature store) | One model and one consumer. A store adds materialization compute and a second copy of the features to keep consistent. | `ml/features.py` is the only definition; `prep` and the app import it, and `test_features` proves both give identical rows. | a second model or a second consumer of the same features |
| **Hyperparameter sweeps** | A sweep cannot give its trials a node identity, and serverless jobs need `id-trainyard-aml` on every node to pull from the admin-disabled shared registry (ADR-006). The gate judges recall at the inspection budget, not a tuning metric. | LightGBM with fixed parameters and seed: the same inputs give the same metrics (REQ-02). | a challenger repeatedly fails the gate on recall |
| **AutoML** | It ranks models by a primary metric, not by recall at the weekly inspection budget. Its ensembles have no exact per-feature contributions, which the explanations of REQ-06 need. It brings its own scoring environment. | `train` fits one `LGBMClassifier`, picks the threshold on validation, and `pred_contrib` gives exact contributions. | a baseline is needed for a new failure mode |

## Consequences

- The platform stays at four components, one environment and one deployment shape. That is what lets the owner read the whole lifecycle in `ml/` (450 lines at most, ADR-003).
- Each row names what would reopen it, so a rejection is not permanent.
