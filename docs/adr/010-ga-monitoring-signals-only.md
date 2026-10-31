# ADR-010 · GA monitoring signals only; predictive quality from matured labels

**Status:** accepted · **Date:** 2026-10-31

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

**Option 1.**

- **One `MonitorSchedule`, `trainyard-monitor`,** defined in `ml/pipeline.py` (`monitor`): classification, the champion deployment as target, no signals listed (so the three GA signals with their defaults), serverless Spark `standard_e4s_v3`, runtime 3.4, daily at 03:15 UTC.
- **The champion is watched, whatever slot it is in.** The promotion calls `watch(slot)` when a model goes to 100 % and when traffic goes back after a rollback (ADR-009).
- **Production runs it every day. Staging creates it disabled** and runs it on demand: `deploy.yml` with the `monitor` input calls `az ml schedule trigger` (ADR-012). Staging pays only for the runs it needs.
- **No e-mail from the monitor:** its creator is the app's managed identity. Alerting stays in Azure Monitor: the scheduled query on `AmlRunStatusChangedEvent` with `Status == "Failed"` notifies the shared action group, and the workbook shows the runs.
- **Predictive quality (KPI-3)** comes from `evaluate`, which scores the champion on the latest window whose labels have matured, in every training run. The app reports it as `model_evaluated`.
- **Latency** is not a monitor signal: the endpoint's `RequestLatency_P95` alert and the traffic log cover it (ADR-014).
- **The chat explains** through `model_status`: the last run's date, the signals, whether it breached, and `breached_at`, the end of the first run of the current breach, where KPI-2 starts.

## State

- **Implemented, type-checked and tested with the double:** the schedule definition in `ml/pipeline.py`, `watch` and `monitor` in `app/azure.py`, the `monitor` input of `deploy.yml`.
- **Pending, live in phase 8:** the first run, the `firmware-b` drift flagged, the alert received, the workbook.
- **NOT VERIFIED until phase 8:**
  - Spark nodes per run, and so the cost (estimate: 2 × E4s_v3 for 15 minutes, about USD 0.28 a run, USD 8.5 a month in production);
  - the experiment name of the monitor's runs, which the app filters on, and whether `AmlRunStatusChangedEvent` carries it;
  - whether a disabled schedule can be triggered;
  - which identity the Spark job runs as, and whether it can write its results to identity-based datastores, since the app identity that creates the schedule only reads storage.

## Consequences

- **Drift means a change between production windows,** not a difference from the training data. `firmware-b` shows as drift because Series B shifts against the days before. A difference present from the first day is not seen as drift; the gate and the matured-label metrics catch a model that is wrong from the start.
- **The staging drift take needs production data before the shift:** scoring traffic on the days before the `firmware-b` feed operation, then traffic after it, then a triggered run.
- **Moving to Option 2** costs one more `prep` output, one MLTable asset per run, and the signals listed explicitly. It is worth it once the model sees real data.
