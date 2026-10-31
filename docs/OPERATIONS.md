# Operations

How Trainyard is run, changed, recovered and paid for. State on 2026-10-31: the infrastructure and the workflows are written and validated with `what-if` in both groups; nothing is deployed yet. Phase 8 fills in every measured figure below, with its date, window and number of cases.

## Environments

| | Staging | Production |
|---|---|---|
| Resource group | `rg-trainyard-stg-swc` | `rg-trainyard-prod-swc` |
| Deploys | every merge to `main` (`deploy.yml`), once `DEPLOY_STAGING` is `true` | a published `v*` release (`release.yml`), after the owner's approval |
| Container App | `ca-trainyard-stg`, 0 to 2 replicas | `ca-trainyard-prod`, 0 to 3 replicas |
| Endpoint | `ep-trainyard-stg`, 1 × `Standard_DS1_v2` while a deployment exists | `ep-trainyard-prod`, the same |
| Monitor | on demand | daily at 03:15 UTC |
| Budget | USD 60, alerts at 80 % actual and 100 % forecast | USD 80, the same |

Each environment has its own identities, workspace, storage, Key Vault, Application Insights, Cosmos DB and Container Apps environment. The shared base (registry, Foundry, Log Analytics, action group) belongs to the landing zone.

## Delivery

- **Switch.** `deploy.yml` runs only when the repository variable `DEPLOY_STAGING` is `true`. Phase 8 sets it once the sign-in app registration exists, so that no merge creates billed resources before the owner has seen the price.
- **One image per commit.** `deploy.yml` builds the image once, tagged `YYYYMMDD-main-<sha>`, and deploys it by digest. A re-run or a feed operation on the same commit reuses that image. The digest is recorded on the commit as the status `staging-image`.
- **Every deployment** (`.github/actions/ship`):
  1. reads the endpoint's live and mirrored traffic;
  2. runs `what-if`, then deploys `infra/main.bicep` with that traffic unchanged;
  3. checks `/healthz`;
  4. registers the four ML components with the image's version (the release tag in production).
- **Production** takes the digest that staging runs for the tag's commit. It is refused unless that commit has successful `load-test/normal`, `load-test/peak` and `load-test/endurance` statuses (REQ-07, REQ-08).
- **Fleet feed operations** (ADR-012) are `workflow_dispatch` inputs of `deploy.yml` and `release.yml`: `feed_days` (days from 2025-11-01) and `firmware_b_from` (the drift scenario). Each one registers a new `fleet-feed` version, logged in the Actions history. Never from a laptop.
- **Urgent patches** go through a `fix/` branch, the same CI and a patch release. They are pre-approved: the owner's approval of the production environment is the change approval.

## Model promotion and rollback

- **Promotion** happens in the chat, by a `ModelApprover`: shadow at 20 % mirrored traffic, canary at 10 % with an automatic health check, then 100 % (ADR-009).
- **Model rollback:** one step inside the window, back to the previous deployment. After the window, promote the previous model version through the same workflow.
- **Never run blue/green in both environments at once.** The DSv2 quota (6 cores) holds staging, production and one pair (ADR-005).
- **Do not merge while a promotion step is running.** A deployment reads the traffic seconds before it applies it, and would undo a change made in between (ADR-004).

## Image rollback

1. Staging: run `deploy.yml` with the earlier image's `digest`.
2. Production: run `release.yml` on the earlier `v*` tag. The production environment accepts only `v*` tags, with the owner's approval.

## Alerts and who receives them

Every alert goes to the shared action group `ag-aiplatform-shared`; the budget alerts go to `ALERT_EMAIL_ADDRESS`. The owner receives both.

| Alert | Fires when | Runbook |
|---|---|---|
| `alert-trainyard-<env>-endpoint-5xx` | any 5xx on the endpoint over 15 minutes | console log (`AmlOnlineEndpointConsoleLog`) → roll traffic back if a canary is live |
| `alert-trainyard-<env>-endpoint-p95` | `RequestLatency_P95` above 400 ms for 15 minutes | workbook SLA tiles → endpoint metrics by deployment |
| `alert-trainyard-<env>-app-5xx` | more than 5 server errors from the app in 15 minutes | App Insights failures → `/healthz` → the dependency named in the error |
| `alert-trainyard-<env>-run-failed` | a failed run in the workspace, split by experiment: a pipeline failure or a monitor breach | workbook → `model_status` in the chat → retrain → promote |
| `budget-trainyard-<env>` | 80 % of the month's budget spent, or 100 % forecast | delete the idle endpoint deployment |

A failed canary rolls itself back; investigate it afterwards from the shadow and canary cards and the endpoint metrics by deployment.

## Incident procedure

1. **Detect:** an alert, the workbook's health model (inference, chat, pipeline, drift), or a user.
2. **Contain:** roll the model or the image back as above. Model traffic changes are immediate; an image rollback is one workflow run.
3. **Diagnose:** console and event logs of the endpoint, App Insights for the app, `AmlRunStatusChangedEvent` for the pipeline and the monitor.
4. **Recover and record:** fix through a `fix/` branch, and note the incident and its timeline in the pull request.

The owner does every step: there is no on-call rotation for a portfolio product.

## Backup and restore

- **Cosmos DB:** continuous backup, 7-day tier, which bills no backup storage. Restore to a new account at a point in time, then point `COSMOS_ENDPOINT` at it. The drill runs in staging in phase 8 and measures RTO (target 4 h) and RPO (target 24 h).
- **Models and data assets** are immutable versions in each workspace. Storage has blob and container soft delete for 7 days.
- **The workspace** is rebuilt from the Bicep and retrained from its data assets.

## Switching on and off

| To | Do |
|---|---|
| Stop the hourly cost of an environment | delete its endpoint deployments; the endpoint, models and data stay |
| Stop the daily monitor | disable the production `MonitorSchedule` |
| Stop deployments to staging | set `DEPLOY_STAGING` to anything but `true` |
| Switch staging on again | run `deploy.yml`, then promote a model from the chat |

Container Apps, the workspace, Cosmos DB serverless and serverless compute cost nothing while idle. **Staging ends every phase at zero,** except the endpoint, whose cost the phase close states.

## Cost per environment

The estimate is in `docs/cost.md`: about USD 52 a month at rest in staging and USD 61 in production, mostly the endpoint. Phase 8 compares it with Cost Management, per resource group.

## Load tests

`load-test.yml`, manual, against staging, before every production promotion. It runs Locust on the endpoint (with `aad_token`) and on `/api/fleet/risk`, which uses no language model:

| Scenario | Users | Duration | Gate |
|---|---|---|---|
| normal | 5 | 5 min | REQ-07 and REQ-08 |
| peak | 50 | 2 min | REQ-07 and REQ-08 |
| stress | ramp of 1 user a second up to 300 | until errors exceed 1 % or p95 exceeds 500 ms | none: it finds the breaking point |
| endurance | 10 | 30 min | REQ-07 and REQ-08 |
| chat | 2 | 2 min | none: it measures the time to first event |

Results: pending, phase 8. Each run's p50, p95, p99, requests per second, errors, peak endpoint CPU and memory, and app replicas go to its job summary and here, with the date.

## DORA metrics

Computed from the Actions runs, with `gh run list --workflow <name> --json conclusion,createdAt,headSha`:
- **Deployment frequency:** successful `release.yml` runs per month (production) and `deploy.yml` runs (staging).
- **Lead time for changes:** from a commit's merge to the `release.yml` run that deployed it.
- **Change failure rate:** releases followed by an image rollback or a `fix/` release, divided by releases.
- **Time to restore:** from a failed release, or an alert, to the run that restored service.

Measured in phase 9, over the project's own history.
