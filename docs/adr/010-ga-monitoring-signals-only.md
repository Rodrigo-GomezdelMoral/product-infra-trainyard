# ADR-010 · GA monitoring signals only; predictive quality from matured labels

**Status:** accepted · **Date:** 2026-10-31 · **Amended:** 2026-11-02, the reference is the training data

## Context

REQ-04 asks that drift, data quality, predictive quality and latency be watched for the model owner: a daily monitor flags a problem, an alert reaches the action group, the workbook shows it and the chat explains it.

Azure Machine Learning model monitoring has three GA signals for a tabular model: data drift, prediction drift and data quality. Feature attribution drift and model performance are preview, and the requirements exclude preview signals. A label matures 7 days after its prediction, because the label is a failure within the next 7 days.

Learn (how-to-monitor-model-performance, 2026-02-11) describes the out-of-box setup:

- it finds the production inference data asset of an online deployment, which the data collector of `ml/score.py` writes (ADR-008);
- it compares that data with **recent past production data**, with default thresholds;
- it runs data drift, prediction drift and data quality on serverless Spark (`standard_e4s_v3`, runtime 3.4);
- a run that breaches a threshold ends Failed with the tag `azureml_modelmonitor_threshold_breached`;
- by default, it e-mails whoever created the monitor.

## Options

1. **Out-of-box monitoring of the champion deployment,** with predictive quality measured by the training pipeline on matured labels.
2. **Advanced monitoring with the training data as reference.** It would also catch a difference between training and serving from the first day. The reference must be an MLTable asset, so `prep` would need a second output and every run a second asset version.
3. **The preview model performance signal,** joined with ground truth by correlation id. The requirements exclude preview signals.
4. **A monitoring job of our own.** It rebuilds what the service gives.

## Decision

**Option 1 until 2026-11-02, then Option 2, decided by the owner before production:** the monitor compares production with the data the champion was trained on, the train split of its `fleet-feed` version.

- **One `MonitorSchedule`, `trainyard-monitor`,** defined in `ml/pipeline.py` (`monitor`): classification, the champion deployment as target, serverless Spark `standard_e4s_v3`, runtime 3.4, daily at 03:15 UTC, the three GA signals with the SDK's default thresholds.
- **The reference is training data.** `prep` writes a fourth output, `reference` (`mltable`): the train rows with exactly the columns the scoring request sends (`unit` and the features) and an `MLTable` file. The pipeline registers it as the data asset `trainyard-reference`, version = the pipeline job's name, which is also the model's `pipeline_job` tag. `reference()` follows the deployment's model to that asset. Data drift and data quality use it as reference with the `training` context; prediction drift keeps the out-of-box reference, the deployment's earlier outputs, because training data has labels, not predicted probabilities. Production data is the collected `model_inputs` and `model_outputs`, filled in by the SDK.
- **A model trained before 2026-11-02 has no reference asset** (versions 1 to 3 in staging): its schedule falls back to the out-of-box definition (production against recent past production).
- **The champion is watched, whatever slot it is in.** The promotion calls `watch(slot)` when a model goes to 100 % and when traffic goes back after a rollback (ADR-009).
- **Production runs it every day. Staging creates it disabled** and runs it on demand: `deploy.yml` with the `monitor` input calls `az ml schedule trigger` (ADR-012). Staging pays only for the runs it needs.
- **No e-mail from the monitor:** its creator is the app's managed identity. Alerting stays in Azure Monitor: the scheduled query on `AmlRunStatusChangedEvent` with `Status == "Failed"` notifies the shared action group, and the workbook shows the runs.
- **Predictive quality (KPI-3)** comes from `evaluate`, which scores the champion on the latest window whose labels have matured, in every training run. The app reports it as `model_evaluated`.
- **Latency** is not a monitor signal: the endpoint's `RequestLatency_P95` alert and the traffic log cover it (ADR-014).
- **The chat explains** through `model_status`: the last run's date, the signals, whether it breached, and `breached_at`, the end of the first run of the current breach, where KPI-2 starts.

## State

- **Implemented, type-checked and tested with the double:** the schedule definition in `ml/pipeline.py`, `watch` and `monitor` in `app/azure.py`, the `monitor` input of `deploy.yml`.
- **Implemented and tested on 2026-11-02, pending live:** the `reference` output of `prep` (`test_components_local` reads its columns), its registration and the signals' references (`test_pipeline_builds`); live, the first training run after the merge registers `trainyard-reference`, and the next promotion of that model creates the schedule with it. Read live in staging on 2026-11-02: `reference()` returns none for model 2 on `blue`, so its schedule stays out-of-box; listing a data name that was never registered raises ("container was not found"), so `reference()` reads the one version it needs.
- **Pending, live in phase 8:** the first run, the `firmware-b` drift flagged, the alert received, the workbook.
- **NOT VERIFIED until phase 8:**
  - Spark nodes per run, and so the cost (estimate: 2 × E4s_v3 for 15 minutes, about USD 0.28 a run, USD 8.5 a month in production);
  - the experiment name of the monitor's runs, which the app filters on, and whether `AmlRunStatusChangedEvent` carries it;
  - whether a disabled schedule can be triggered;
  - which identity the Spark job runs as, and whether it can write its results to identity-based datastores, since the app identity that creates the schedule only reads storage.

## Consequences

- **Drift means a difference from the training data,** so a training-serving skew shows from the first run, and `firmware-b` shows as drift as soon as Series B's shifted rows are scored by a model trained before it. The staging drift take needs no traffic from before the shift.
- **Every training run registers one more data asset version,** a few hundred kilobytes of parquet in the workspace storage; refused challengers keep theirs, which costs cents and keeps every run auditable.
- **The signals are listed explicitly,** built from the SDK's own default signals (`_get_default_*_signal`, private classmethods of the pinned `azure-ai-ml==1.35.2`), so the thresholds stay the out-of-box ones; a bump of the SDK re-runs `test_pipeline_builds`, which checks the reference of each signal.
- **Prediction drift stays production against production:** the probabilities of a new model are compared with its own earlier outputs.
