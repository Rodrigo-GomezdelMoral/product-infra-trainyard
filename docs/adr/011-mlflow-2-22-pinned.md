# ADR-011 · MLflow 2.22, pinned

**Status:** accepted · **Date:** 2026-10-31

## Context

Every step logs to MLflow, and `register` registers the model through MLflow in the workspace's registry (REQ-01, REQ-02). `azure-care-intelligence-platform` measured on 2026-10-20 that the workspace's tracking backend answers 404 to MLflow 3's `/logged-models` endpoint, so every `log_model` fails, and to `/registered-models/alias`. `azureml-mlflow` up to 1.62 also declares `mlflow-skinny<=3.15`.

## Options

1. **MLflow 3,** with champion and challenger as model aliases. It fails against the workspace, as measured.
2. **MLflow 2.22 with stage tags** (`champion`, `challenger`) on model versions, as care-intel does. The tags are a second source of truth, which can say "champion" about a model that no longer serves anyone.
3. **MLflow 2.22, with no stage at all.** The champion is whatever serves 100 % of live traffic on the endpoint (ADR-009). A version carries only what does not change: its lineage, its metrics and its operating point.

## Decision

**Option 3.** `mlflow==2.22.5` and `azureml-mlflow==1.62.0.post6` are pinned in the Azure Machine Learning environment. `mlflow==2.22.5` is also pinned on the laptop and in CI.

- **The registered version carries tags:**
  - its lineage: `git_sha`, `data_asset`, `data_version`, `pipeline_job`;
  - `gate`, and the `champion` it was compared with;
  - its holdout metrics, written with four decimals.
- **The MLmodel file carries `metadata`:** the calibration and the threshold, which travel with the model into any deployment (ADR-008).
- **Each step opens one explicit `mlflow.start_run`,** tagged with the step's name. Inside an Azure Machine Learning job, that call attaches to the job's run.
- **Local runs** log to a file store in `.local/mlruns`, which has a model registry, so `make train-local` registers real versions on the laptop.
- **`pyarrow==19.0.1`**, because MLflow 2.22 requires `pyarrow<20`.
- **Dependabot ignores major bumps** of `mlflow` and `pyarrow`, as it already does for `pandas`.

## State

**Implemented and tested** with local stores: `test_components_local` and `test_register_tags_lineage`. The registered version's tags, and its calibration after a download through `models:/`, match what was logged.

**Pending:** the same calls against the workspace's tracking URI (phase 8).

## Consequences

- **MLflow 2.22 warns on Python 3.12:**
  - it calls `datetime.utcnow()`;
  - importing `mlflow.pyfunc` warns about its own type hints.

  The tests turn warnings into errors, so `pyproject.toml` ignores exactly those two, together with the Marshmallow 4 deprecations that `azure-ai-ml` raises on import. Every other warning still fails the suite.
- **`mlflow.lightgbm.save_model` creates the default store** in the working directory. The tests therefore point MLflow at a temporary store for the whole session, and the Makefile points it at `.local/mlruns`.
- **Revisit** when `azureml-mlflow` accepts MLflow 3 and the workspace answers its endpoints. Nothing in Trainyard depends on aliases, so the move would be a version bump.
