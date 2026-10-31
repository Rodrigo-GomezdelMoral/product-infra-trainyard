# ADR-008 · A custom `score.py` with the data collector

**Status:** accepted · **Date:** 2026-10-31

## Context

The endpoint must answer the planner's question for the whole fleet within the latency SLA: p95 under 500 ms for up to 40 rows (REQ-08). Every answer must explain each unit with its top signals and name the model that scored it (REQ-06, REQ-01). The monitor needs the production inputs and outputs, collected as data assets (REQ-04). The agent's tools already rely on a contract (ADR-001): a probability and per-feature contributions for each unit, plus the model version and its operating threshold.

## Options

1. **MLflow no-code deployment.** Azure Machine Learning generates the scoring script and the environment from the MLflow model.
   - It returns only what the flavor's `predict` returns, with no contributions, threshold or version.
   - It cannot be run on a laptop before deployment.
   - Its data collection is documented as a studio switch for MLflow models.
2. **A custom container** with its own HTTP server and inference configuration. Everything would be ours to maintain, from the server to the probes.
3. **A custom `score.py` on the Azure Machine Learning inference server,** with the `azureml-ai-monitoring` collector, in the environment the training steps use.

## Decision

**Option 3**, in `ml/score.py`.

### The contract

The request is `{"rows": [...]}`: one feature row per unit, the columns of `ml/features.py`, and the unit.

The answer has three fields:
- `model_version`;
- `threshold`, the model's operating point;
- `scores`: for each unit, the calibrated 7-day failure probability and every feature's contribution in log-odds.

### How it is computed

- **Exact contributions.** They are LightGBM's own `pred_contrib`, scaled by the Platt calibration (ADR-003). With the base value and the calibration's shift, they add up to the logit of the probability returned. The explanation is therefore exact, not an approximation such as a separate SHAP model.
- **Every contribution is returned, not only the top three.** The app picks the top three positive contributions among the signals a planner can read (`app/domain/fleet.py`). If the endpoint cut to three, `series_b` or `observed_days`, which have no plain-language template, could crowd the readable signals out.
- **The threshold and the calibration travel with the model,** in the MLmodel file's `metadata`. A registered version carries its own operating point, so an answer can never mix one model's scores with another's threshold.
- **Only the contributions are rounded,** to four decimals. The probability and the threshold are returned exactly. If they were rounded too, a unit within 1e-4 below the threshold could be flagged by the app although the gate never counted it.
- **The model version** is the last folder of `AZUREML_MODEL_DIR`. Learn's scoring example documents that path as `./azureml-models/$MODEL_NAME/$VERSION` (2026-03-26).
- **One scorer for the gate and for serving.** `Scorer` is the code that serves, and `evaluate` imports it, so the gate measures exactly what users will get.
- **The module imports nothing from the repository.** A deployment's code snapshot is the `ml/` folder, mounted under the application root, where `ml` is not importable as a package (measured in care-intel).

### Collection

The collectors are named `model_inputs` and `model_outputs`, the names that model monitoring recognises without extra configuration (Learn, how-to-collect-production-data, 2026-01-21). `model_outputs` holds the unit and its probability, correlated with the inputs through the context that the first `collect` returns.

`on_error` logs instead of raising. Learn notes that the collector raises by default, and in the installed 1.0.0 it raises as soon as it is created when collection is off. Without `on_error`, a deployment without a data collector would fail every request.

### Run locally, as the endpoint runs it

The base image's runit service, `/var/runit/gunicorn/run`, ends with `cd $AML_APP_ROOT` and `exec azmlinfsrv --entry_script $AZUREML_ENTRY_SCRIPT`. `make score-local` reproduces it:

1. It builds `ml/environment`, the same build context the workspace builds (ADR-003).
2. It mounts `ml/` and a model where a deployment mounts them.
3. It starts `azmlinfsrv` with the collector's own local capture: `AZUREML_MDC_ENABLED` and `AZUREML_MDC_LOCAL_CAPTURE` make it log every payload through the `local.capture` logger.
4. It runs `tests/test_scoring.py` against it over HTTP.

The SDK's local endpoints (`local=True`) were considered. They would need placeholder workspace values in an `MLClient` and write their build files under the user's home folder, for the same container.

## State

**Implemented and tested.**

- `test_score_latency_local`: 40 rows, in process or over HTTP.
- `test_collector_logs`: inputs and outputs collected with the same correlation id.

**Measured on 2026-10-31,** with Docker Desktop on a laptop, the model from `make train-local` and the 40 units of 2026-01-26 in the test feed:

- **Build.** The environment built in 122 s into a 2.74 GB image, and `pip check` reported no broken requirement.
- **Answer.** EMU 2417, which fails two days later, scored 0.989, and the app's `plan` listed it with its signals.
- **Latency.** Over HTTP, 200 requests of 40 rows took p50 24 ms, p95 45 ms, p99 57 ms and at most 91 ms.
- **Collection.** The collector captured 400 payloads: an input and an output for each request.

**Pending:**

| Piece | Phase |
|---|---|
| Deployments created by the promotion workflow with `DataCollector` for both collections | 8 |
| The collected data assets in the workspace storage | 8 |
| p95 on `Standard_DS1_v2` under the Locust scenarios | 8 |

## Consequences

- **The laptop is not the SLA.** One `Standard_DS1_v2` instance has one vCPU, against a laptop's many. The SLA is measured in staging (phase 8).
- **The answer for 40 units is about 12.6 KB** (11.1 KB request), with every contribution included. That is small, and it keeps the explanation on the app's side.
- **With collection off, scoring still works.** Without the collector's configuration, `on_error` logs "custom logging is not enabled, drop the data" and the request is answered (seen in a local run).
- **One environment for training and scoring.** The inference server and the collector are installed in the training jobs too.
  - That is the price of building one image.
  - The inference server pins OpenTelemetry 1.33, which Agent Framework cannot share. It never enters the app's environment, and the app's tests do not need it.
