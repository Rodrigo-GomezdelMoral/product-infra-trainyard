# Changelog

All notable changes to Trainyard are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
