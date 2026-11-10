# ADR-011 · MLflow 2.22, pinned

**Status:** accepted · **Date:** 2026-10-31 · **Amended:** 2026-11-04, production lineage and the Dependabot assessment

## Context

Every step logs to MLflow, and `register` registers the model through MLflow in the workspace's registry (REQ-01, REQ-02). An earlier Azure Machine Learning deployment measured on 2026-10-20 that the workspace's tracking backend answers 404 to MLflow 3's `/logged-models` endpoint, so every `log_model` fails, and to `/registered-models/alias`. `azureml-mlflow` up to 1.62 also declares `mlflow-skinny<=3.15`.

## Options

1. **MLflow 3,** with champion and challenger as model aliases. It fails against the workspace, as measured.
2. **MLflow 2.22 with stage tags** (`champion`, `challenger`) on model versions, as that earlier deployment does. The tags are a second source of truth, which can say "champion" about a model that no longer serves anyone.
3. **MLflow 2.22, with no stage at all.** The champion is whatever serves 100 % of live traffic on the endpoint (ADR-009). A version carries only what does not change: its lineage, its metrics and its operating point.

## Decision

**Option 3.** `mlflow==2.22.5` and `azureml-mlflow==1.62.0.post6` are pinned in the Azure Machine Learning environment. `mlflow==2.22.5` is also pinned on the laptop and in CI.

- **The registered version carries tags:**
  - its lineage: `git_sha`, `data_asset`, `data_version`, `pipeline_job`. `git_sha` is the last segment of the component version (`ml/pipeline.py:84`): the short commit in staging (`YYYYMMDD-main-<sha>`) and the release tag in production (model 1 reads `v1.0.0`). A `v*` tag resolves to one commit, and the ruleset `protect-release-tags` forbids moving or deleting it (decided on 2026-11-04, instead of an `ml/` change that would need the release load tests);
  - `gate`, and the `champion` it was compared with;
  - its holdout metrics, written with four decimals.
- **The MLmodel file carries `metadata`:** the calibration and the threshold, which travel with the model into any deployment (ADR-008).
- **Each step opens one explicit `mlflow.start_run`,** tagged with the step's name. Inside an Azure Machine Learning job, that call attaches to the job's run.
- **Local runs** log to a file store in `.local/mlruns`, which has a model registry, so `make train-local` registers real versions on the laptop.
- **`pyarrow==19.0.1`**, because MLflow 2.22 requires `pyarrow<20`.
- **Dependabot ignores major bumps** of `mlflow` and `pyarrow`, as it already does for `pandas`.

## State

**Implemented and tested** with local stores: `test_components_local` and `test_register_tags_lineage`. The registered version's tags, and its calibration after a download through `models:/`, match what was logged.

**Live:** the same calls against the workspaces' tracking URIs: staging registered versions 1 to 6 from 2026-11-01, production version 1 on 2026-11-03, each with its lineage tags and `gate: passed`.

## Dependabot assessment (2026-11-04)

Dependabot opened 29 alerts on `requirements*.txt`: 27 on `mlflow==2.22.5` (7 critical, 14 high, 5 medium, 1 low) and 2 on `pyarrow==19.0.1` (high). Trainyard calls only `mlflow.start_run`, `log_params`, `log_metrics`, `mlflow.lightgbm.save_model`, `log_model` and `load_model`, `register_model` and `mlflow.models`; tracking goes to Azure Machine Learning. It never runs `mlflow server`, `mlflow ui`, the AI Gateway, `mlflow models serve`, MLServer, SageMaker, Databricks Connect, autologging, `mlflow.data` or the statsmodels flavor. MLflow is in the Azure Machine Learning environment (`ml/environment/conda.yaml`, which Dependabot does not read) and the dev requirements, never in the app image. Each alert is dismissed with its reason and a one-line comment:

- **Not used (22 MLflow alerts):** the tracking server, its UI and basic-auth app, the AI Gateway, the model server and its container, SageMaker, the Databricks Connect cache, CrewAI autologging, `mlflow.data` digests and the statsmodels flavor: #2, 4, 5, 6, 8 to 17, 19 to 23, 25, 26 and 28.
- **Tolerable risk (5 MLflow alerts, client side):** #1 (deserialization of an untrusted PyTorch model), #3 and #24 (world-writable temporary directories), #7 (tar traversal in pyfunc extraction) and #27 (trace ids in the file store, reached through a server that never runs; the local store serves only `make train-local`). Each touches only Trainyard's own gated artifacts, on single-tenant, ephemeral CI runners and job nodes.
- **pyarrow, not used (#18, #29):** the advisory is a use-after-free when reading Arrow IPC files with pre-buffering; Trainyard reads only Parquet of its own synthetic feed (`app/azure.py`, `ml/steps.py`). 23.0.1 waits for MLflow 3, since MLflow 2.22 requires `pyarrow<20`.
- **Pull requests:** #11 (mlflow 3) and #16 (pyarrow 23) closed, as above; #13 (node 26) and #14 (python 3.15) closed, with `ignore` rules for the docker ecosystem; #3 (numpy 2.4.6) and #6 (the Azure Machine Learning base image's dated tag) wait for the next runtime release and its load tests.

## Consequences

- **MLflow 2.22 warns on Python 3.12:**
  - it calls `datetime.utcnow()`;
  - importing `mlflow.pyfunc` warns about its own type hints.

  The tests turn warnings into errors, so `pyproject.toml` ignores exactly those two, together with the Marshmallow 4 deprecations that `azure-ai-ml` raises on import. Every other warning still fails the suite.
- **`mlflow.lightgbm.save_model` creates the default store** in the working directory. The tests therefore point MLflow at a temporary store for the whole session, and the Makefile points it at `.local/mlruns`.
- **Revisit** when `azureml-mlflow` accepts MLflow 3 and the workspace answers its endpoints. Nothing in Trainyard depends on aliases, so the move would be a version bump.
