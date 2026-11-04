# Changelog

All notable changes to Trainyard are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.2] - 2026-11-05

Documentation only: since `v1.0.1`, only `docs/` and `CHANGELOG.md` changed, so `release.yml` needs the staging deploy of
the tag's commit but no load test (ADR-019). The API, the model code and the infrastructure are unchanged.

### Added

- **The image rollback drill, measured.** On 2026-11-04 staging went back to `v1.0.0`'s image in 4 min 20 s and forward
  in 3 min 30 s; production went back to `v1.0.0` in 12 min 29 s and forward to `v1.0.1` in 5 min 3 s, the owner's
  approval included. Both endpoints kept their model (`docs/OPERATIONS.md`, *Image rollback*).

## [1.0.1] - 2026-11-04

Documentation, the recorded demo runs, the demo recorder (`ops/`) and workflows only: no runtime path changed since
`v1.0.0`, so the release load tests are not required (ADR-019, which now also exempts `ops/`). It closes the validation of `v1.0.0`.

### Added

- **The published demo.** Runs recorded from the production deployment (`web/src/demo/runs`), replayed by the Pages site
  with their real timings: the inspection list, a unit's explanation and lineage, the drift question, an approved
  retraining, a shadow, canary and promotion, and a `Reader` refused.
- **Production evidence.** Requirements, KPIs and DORA metrics with production values, date and number of cases
  (README, `docs/OPERATIONS.md`); measured costs per meter (`docs/cost.md`); the released code's evaluation run
  (`docs/evaluation.md`); the language model's retirement date and replacement plan (`docs/RESPONSIBLE_AI.md`).

### Changed

- **The load-test figures** are those of the release commit `0246d04`: endurance 9,676 requests at 5.38 a second, 0
  failed, p95 389 ms; peak 600 requests, 0 failed, p95 429 ms; normal 852 requests, 0 failed, p95 226 ms. The `6d091cf`
  runs stay as history in `docs/OPERATIONS.md`.
- **The chat SLO** is reported on the whole streamed turn until the first event is instrumented (ADR-014).
- **`AUTH_CLIENT_ID`** is read from an environment secret, so GitHub masks it in every log line.
- **Dependabot** ignores major bumps of the `node` image and major and minor bumps of the `python` image.

### Fixed

- **The demo recorder waited forever on the shadow.** The shadow card keeps the readiness it was asked with and the app
  measures it again only when the owner answers, so `ops/record.py` now stops waiting after 30 minutes and answers
  Start canary again each minute while the app asks for the shadow again.
- **Stale state lines** that said production was not deployed (`docs/OPERATIONS.md`, `docs/THREAT_MODEL.md`,
  `docs/RESPONSIBLE_AI.md`, README); the run-failed alert's description, which is split by run, not by experiment, and
  its blind spot for runs that never leave Queued; the first production deployment's prerequisites, which made the
  `v1.0.0` run fail twice; conversations keep a SHA-256 prefix of the object id, not the id.

### Security

- **Dependabot assessment.** The 29 alerts on `mlflow==2.22.5` and `pyarrow==19.0.1` are assessed one by one and
  dismissed with their reason: 24 affect code Trainyard never runs, 5 touch only its own gated artifacts (ADR-011).
- **Release tags** `v*` cannot be moved or deleted, so production's lineage tag, the release tag, names one commit.

### Known limitations

- **REQ-04 is NOT VERIFIED, a platform limitation.** Production's first monitor run (2026-11-04, 03:15 UTC) stayed
  Queued for 11 hours: the service submits its preprocessing steps on serverless Spark 3.4 although the schedule asks
  for 3.5, as in staging. The run was cancelled and the schedule disabled; KPI-2 cannot be measured (ADR-010).
- **Next runtime release:** the Application Insights daily cap and sampling in Bicep, a digest check in
  `load-test.yml`, the ML base image pinned by digest, the endpoint's telemetry and cloud role name, the chat's
  first-event measurement, and Dependabot PRs #3 and #6.

## [1.0.0] - 2026-11-03

The first release: 7-day failure risk for a fleet of 40 electric multiple units, and a model lifecycle the model owner
governs from the chat. Everything below ran in staging between 2026-11-01 and 2026-11-03; this release deploys the image
staging runs to production. All data is synthetic.

### Added

- **The planner's answer (REQ-06).** "Which trains should we inspect this week?" returns the ranked units within the
  inspection budget, the 7-day failure probability, the top contributing signals and the model version, every number
  copied from the tool's output. One agent (`gpt-5-mini`, Agent Framework), tools for fleet risk, one unit's explanation
  and the model's status (ADR-001).
- **Lineage for every score (REQ-01).** The model version, the training job, the `fleet-feed` data asset version and the
  git commit, in the chat and in Azure Machine Learning studio.
- **Automated training (REQ-02).** `prep → train → evaluate → register` on serverless compute from a data asset
  version, started by a merge, a release or the chat; the gate refuses a challenger that is worse than the champion on the
  same holdout. Model cycle time (KPI-1) in staging: median 7.5 min over 6 runs.
- **Human-approved promotion (REQ-03, REQ-05).** A shadow with mirrored live traffic and an offline comparison, then a
  10 % canary with an automatic health check, then 100 % after a second approval, and a window in which one step rolls
  back. The workflow is checkpointed in Cosmos DB and resumes after a restart (ADR-009). A `Reader` cannot reach any
  approval tool.
- **The monitor (REQ-04).** Data drift, prediction drift and data quality against the training data, daily in
  production and on demand in staging, with a log alert on failed or breached runs and the workbook (ADR-010).
- **The inference SLA (REQ-07, REQ-08).** One `Standard_DS1_v2` managed online endpoint per environment with
  `aad_token`, up to 5 requests a second of 40 rows: availability ≥ 99.5 % a month and p95 < 500 ms (ADR-005, ADR-014).
- **The API and the web client.** FastAPI behind Easy Auth with two app roles, KPI events, 👍/👎 feedback (REQ-09),
  conversation deletion and a 30-day expiry (REQ-10), and the common chat interface with its demo mode.
- **Delivery.** Bicep for both environments, one image per merge promoted by digest, `deploy.yml`, `release.yml`
  (production only from a `v*` tag, after the owner's approval and the load tests), `load-test.yml`, `eval.yml` and
  `pages.yml`, all with GitHub OIDC and no secrets.
- **Operations.** The restore drill (RTO 13 minutes of work against 4 h), alerts, the workbook, the incident procedure,
  cost per environment and per unit, and the DORA metrics (`docs/OPERATIONS.md`).

### Fixed

- **The drift answer.** `model_status` counted a cancelled monitor run as the last run and listed the watched signals as
  `signals`, so the chat said "Signals of drift were detected" when no run had completed. Only completed or breached
  runs count now, the signals are the signals watched, and with no completed run the chat says so.
- **Load tests.** `load-test.yml` signs in again after the scenario, because the OIDC client assertion of
  `azure/login` expires after 5 minutes and the 30-minute endurance could not be judged; it judges only once the
  endpoint's log for the window has fully arrived; peak spawns its 50 users 5 a second, so their requests arrive at an
  even 5 a second instead of bursts of 10; the chat scenario marks each streamed answer itself (`catch_response=True`).

### Known limitations

- **REQ-04's monitor run is NOT VERIFIED.** Serverless Spark does not start in this subscription on runtime 3.4 or 3.5
  (measured on 2026-11-03), so no monitor run has completed and KPI-2 cannot be measured yet (ADR-010).
- **One endpoint instance.** Measured on 2026-11-03: 5.38 requests a second for 30 minutes with 0 failures and p95
  399 ms; the latency SLA breaks at about 7 a second (ADR-005).
