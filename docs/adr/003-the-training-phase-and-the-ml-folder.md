# ADR-003 · The `training` phase and the `ml/` folder

**Status:** accepted · **Date:** 2026-10-31

## Context

REQ-02 asks for training without manual steps, reproducible from the same inputs and seed. REQ-03 asks for every challenger to be compared with the champion before it serves anyone. REQ-04 needs the production inputs and outputs collected for the monitor. All three need code that runs in Azure Machine Learning, not in the Container App: four pipeline steps, a pipeline definition, a scoring script and the environment they run in.

The common product skeleton has nine phases, with `eval` as phase 3, and a single application budget of 1,150 lines. Neither has a place for code that runs as Azure Machine Learning jobs.

## Options

1. **Put the steps under `app/`.** The application image would carry LightGBM, MLflow and scikit-learn, which it never uses, and the 1,150-line budget would mix two runtimes.
2. **A second repository for the model.** The model and the product would then version separately, but REQ-01 traces every score to one git commit, and the promotion workflow (ADR-009) would depend on another repository's release.
3. **A `training` phase between `agents` and `api`, and an `ml/` folder with its own budget:** at most 450 lines of Python and 10 files.

## Decision

**Option 3.** Phase 3 is `feature/training`, so the skeleton's `eval` becomes phase 4.

**Budgets, set by the owner in phase 5 (2026-10-31).** `eval/` and `load/` count as application Python with `app/` (1,150 lines), as in the other products, and the test limit is 850 lines for `tests/` only: the pipeline, the scoring script and the promotion workflow with its lease, which REQ-02, REQ-03 and REQ-05 need, add test surface that the reference product, with 700, does not have.

### What `ml/` holds

Ten files, which is the folder's whole budget:

| File | Role |
|---|---|
| `features.py` | one feature row per unit (phase 1), imported by `prep` and by the app |
| `steps.py` | the four steps, `prep`, `train`, `evaluate` and `register`, and `local`, which runs all four |
| `components/*.yaml` | one command component per step |
| `pipeline.py` | the `@pipeline` definition, on serverless compute |
| `score.py` | the endpoint's scoring script, and the scorer `evaluate` uses (ADR-008) |
| `environment/conda.yaml`, `environment/Dockerfile` | the one environment for training and scoring |

### How the pieces fit

- **The spec is the interface.** Each step's command-line options are read from its component spec: names, types, and defaults, which live only in the YAML. `local` substitutes local paths into the specs' own `command` lines and runs them. A spec that does not match its step therefore fails on a laptop before it fails in the workspace.
- **The code snapshot is `ml/` alone.** The components declare `code: ../..`, so that `python -m ml.steps` imports `ml.features` as the app does. `.amlignore` is an allowlist (`/*`, then `!/ml/`). The SDK's own upload walker lists the ten files of `ml/` and nothing else: no `.venv`, `.local`, `app/` or caches.
- **One environment, built the same way everywhere.** `ml/environment` is a Docker build context: the Azure Machine Learning base image `openmpi4.1.0-ubuntu22.04`, pinned to a dated tag, plus `conda.yaml`. The four components and the deployment declare the same context, so the workspace builds one image, and `make score-local` builds the same one on a laptop.
  - The base image is the one Learn's data-collection article uses, and the one `azure-care-intelligence-platform` ran on serverless jobs and online endpoints.
  - **Not a curated environment**, which the Azure Machine Learning service guide prefers where possible. A curated environment fixes package versions we do not choose. Feature parity needs `numpy` and `pandas` equal to the app's, and the model needs LightGBM, MLflow 2.22 (ADR-011), the inference server and the collector together. So the environment starts from the platform's maintained base image and pins its own packages.
  - `test_environment_pins_match_the_laptop` keeps the pins that both sides share equal, so `ml/features.py` gives the same rows in `prep` and in the app.
- **The app can submit without ML packages.** `ml/pipeline.py` imports only `azure-ai-ml`, so `start_retraining` (phase 8) does not pull LightGBM or MLflow into the application image.

### The model

- **Split by time, never at random.** The last 56 days of matured rows are the holdout, the latest window whose labels have matured (KPI-3). The 56 days before them are validation, and everything earlier is training. There is a 7-day gap between the parts, because a label looks 7 days ahead: no failure is a positive in two parts.
- **LightGBM** (`LGBMClassifier`, 300 trees, 15 leaves) with `deterministic`, `force_row_wise` and one thread. LightGBM promises identical trees only for the same thread count, and a laptop, the CI runner and an F2s_v2 node differ.
- **Calibrated probabilities.** Boosted trees on 2.5 % positives are overconfident. A unit at the operating point read "0 %" in the probes, which is not something a planner can read. A Platt scaling fitted on validation fixes this. It is monotone, so it flags exactly the same units. The scaled LightGBM contributions still add up to the calibrated log-odds, so the explanation stays exact (ADR-008).
- **The operating point** is the lowest threshold on validation whose weekly flags fit the inspection budget, at the KPI-3 precision target:
  - in every validation week, the distinct units flagged stay within the budget (6);
  - at least 60 % of the flags are followed by a failure within 7 days.

  `PRODUCT.md` says "the highest recall whose weekly flags fit the inspection budget". Two readings were measured before choosing. Each feed was 365 days of the default seed, the model was this one, and the figures are holdout results:

  | Rule | Cases | Thresholds chosen, before calibration | Holdout result |
  |---|---|---|---|
  | Budget only, counted on each day's list | 9 | 0.0006 or lower | precision 0.30 to 0.55: the gate fails every time |
  | Distinct units per week within the budget, plus the 60 % target | 6 | 0.001 to 0.004 | precision 0.62 to 0.75, recall 0.895 to 0.940: the gate passes every time |

  The cases are three feed start dates (2025-11-01, 2026-01-01 and 2026-06-01), with 56 validation days and 56 or 84 holdout days, plus 84 and 84 for the first rule. A budget that ignores precision would fill the workshop with healthy trains and never pass the gate it exists for. `PRODUCT.md` now states the rule.
- **The gate is in `evaluate`, and `register` obeys it.** On the holdout, at the challenger's own operating point:
  - recall must be at least 0.80 and precision at least 0.60;
  - no series may have recall below 0.70; a series with no failure in the holdout is not judged;
  - recall may be at most 0.02 below the champion's, measured on the same holdout at the champion's own threshold.

  The reasons are written to the report and logged to MLflow. `register` registers nothing when the gate failed.

## State

**Implemented and tested.** `make train-local` runs on the laptop. Measured on 2026-10-31:

- **A year of feed** from 2025-11-01, default seed, ran prep, train, evaluate and register in 55 s.
  - **Validation:** threshold 0.147, recall 0.857, precision 0.923.
  - **Holdout:** recall 0.899, precision 0.873; Series A 0.919, Series B 0.714 (5 of 7 positives); at most 3 units flagged in any week. The gate passed and version 1 was registered.
- **Reproducibility.**
  - Two runs gave byte-identical reports.
  - Inside the Azure Machine Learning environment (Linux, `make train-local` run in the built image), the metrics were identical to the last digit, and the calibration agreed to about 1e-16.
- **Memory.** With a hard 4 GiB limit, the size of a `Standard_F2s_v2`, `prep` peaked at 952 MiB in 14 s and `train` at 423 MiB in 9 s.
- **The pipeline object** builds and validates offline: four nodes on `Standard_F2s_v2`, each with the user-assigned identity, serverless as default compute, and the champion wired only when one is given (`test_pipeline_builds`).

**Independent review on 2026-10-31.** It found three defects, each reproduced, and all three are fixed:

1. `test_pipeline_builds` checked for the champion in the wrong part of the job, so that assertion could never fail.
2. `local --champion` without `--champion-version` silently dropped the champion comparison. The pair is now required together, and so is `--git-sha`.
3. `score.py` rounded the probability and the threshold, which could add a flag that the gate never measured (ADR-008).

The review confirmed the rest by running it: the split's windows and gaps, the calibration's round trip through `register`, the operating point, the gate's edges, and that `register` registers only what passed.

**Pending:**

| Piece | Phase |
|---|---|
| Registering the components and the environment with the image's version from `deploy.yml` | 7 |
| The first live run on serverless compute | 8 |
| The workspace building the environment from the build context (NOT VERIFIED; the fallback is the image plus conda file that care-intel measured) | 8 |

## Consequences

- **`ml/` is full** at 10 of 10 files. A new ML file replaces one, or this ADR changes.
- **`test_components_local` starts four real processes,** about 35 s on a Windows laptop. It is the only test that proves the specs' command lines.
- **Measured quality is better than a real fleet would allow,** because every failure in the synthetic feed has a precursor (ADR-012).
- **Series B's recall is judged on few events:** 7 positive rows, from 1 or 2 failures, in a 56-day holdout. One missed failure can fail the gate. That is the intended behaviour of a floor, and the report says which series failed.
- **Dependabot pins move in pairs.** Dependabot updates `requirements*.txt`, not `conda.yaml`. A version bump that touches a shared package fails `test_environment_pins_match_the_laptop` until the same pull request updates `conda.yaml`.
