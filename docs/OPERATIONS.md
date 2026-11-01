# Operations

How Trainyard is run, changed, recovered and paid for. State on 2026-11-01: staging is deployed and serves a model; production is not deployed yet. Every measured figure below carries its date, window and number of cases.

## Environments

| | Staging | Production |
|---|---|---|
| Resource group | `rg-trainyard-stg-swc` | `rg-trainyard-prod-swc` |
| Deploys | every merge to `main` (`deploy.yml`), once `DEPLOY_STAGING` is `true` | a published `v*` release (`release.yml`), after the owner's approval |
| Container Apps environment | `cae-trainyard-stg-gwc`, Germany West Central | `cae-trainyard-prod-gwc`, Germany West Central |
| Container App | `ca-trainyard-stg`, 0 to 2 replicas | `ca-trainyard-prod`, 0 to 3 replicas |
| Endpoint | `ep-trainyard-stg`, 1 × `Standard_DS1_v2` while a deployment exists | `ep-trainyard-prod`, the same |
| Monitor | on demand | daily at 03:15 UTC |
| Budget | USD 60, alerts at 80 % actual and 100 % forecast | USD 80, the same |

Each environment has its own identities, workspace, storage, Key Vault, Application Insights, Cosmos DB and Container Apps environment. Everything is in Sweden Central except the Container Apps environment and the app, in Germany West Central. Sweden Central allows one Container Apps environment per subscription, and another product uses it; West Europe refuses new resources from this subscription (ADR-017). Each call from the app to Cosmos DB, the endpoint or the workspace adds a 27 ms round trip. The shared base (registry, Foundry, Log Analytics, action group) belongs to the landing zone.

## Delivery

- **Switch.** `deploy.yml` runs only when the repository variable `DEPLOY_STAGING` is `true`. Phase 8 sets it once the sign-in app registration exists, so that no merge creates billed resources before the owner has seen the price.
- **One image per commit.** `deploy.yml` builds the image once, tagged `YYYYMMDD-main-<sha>`, and deploys it by digest. A re-run or a feed operation on the same commit reuses that image. The digest is recorded on the commit as the status `staging-image`.
- **Every deployment** (`.github/actions/ship`):
  1. reads the endpoint's live and mirrored traffic, by the endpoint's name: a failed deployment has no outputs, and an empty traffic would send no request to any deployment; only a missing endpoint reads as empty, and any other error stops the run, as does an endpoint whose creation failed (see *A failed endpoint*);
  2. runs `what-if`, then deploys `infra/main.bicep` with that traffic unchanged, and retries a failed deployment once after 10 minutes, Learn's bound for a new role assignment to take effect (ADR-006);
  3. checks `/healthz`;
  4. registers the four ML components with the image's version (the release tag in production).
- **The owner's identity scripts** live outside the repository and run once, in order: `00-github.sh` and `01-azure.sh` (setup); `02-shared-access.sh` (deployments and monitoring links in the shared group); `03-login.sh <env>` (the sign-in app registration, run again after the first deployment to register the callback URL); `04-staging-access.sh` (Monitoring Reader in the conditions, and `DEPLOY_STAGING`); `05-registry-link.sh` (`registries/read` and `/write` on the shared registry, which ARM checks at every PUT of a workspace that links it, ADR-007); `06-endpoint-providers.sh` (registers `Microsoft.PolicyInsights` and `Microsoft.Cdn`, and deletes the staging endpoint only if its creation failed). The CI principals' roles and conditions change only through these scripts; the workflows create only the role assignments the Bicep declares, within those conditions.
- **Production** takes the digest that staging runs for the tag's commit. It is refused unless that commit has successful `load-test/normal`, `load-test/peak` and `load-test/endurance` statuses (REQ-07, REQ-08).
- **Fleet feed operations** (ADR-012) are `workflow_dispatch` inputs of `deploy.yml` and `release.yml`: `feed_days` (days from 2025-11-01) and `firmware_b_from` (the drift scenario). Each one registers a new `fleet-feed` version, logged in the Actions history. Never from a laptop. The staging drift scenario uses `feed_days=365` and `firmware_b_from=2026-05-01`, run on 2026-11-01. A local rehearsal with the same code chose that date: with the shift from May, a retrained model keeps recall 0.90 and Series B recall 0.71 on the new holdout while the current model drops to 0.84 and 0.14, so the gate registers the challenger and the comparison favours it; with the shift from August, too little of it reaches the training window and the challenger fails the gate on Series B (0.14).
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

### A failed endpoint

Azure ML accepts no update to an endpoint whose creation failed ("Please recreate the endpoint"), so the deployment stops before `what-if`. Fix the cause, delete the endpoint (it has no deployment and no traffic) and run the deployment again: the Bicep recreates it. On the first staging deployment the cause was `SubscriptionNotRegistered`: a managed online endpoint needs `Microsoft.PolicyInsights` and `Microsoft.Cdn` registered in the subscription, which Learn's troubleshooting page does not list. `06-endpoint-providers.sh` registers both and deletes the staging endpoint only in that state. Deleting an endpoint is never automatic, because in production it is the SLA surface.

## Backup and restore

- **Cosmos DB:** continuous backup, 7-day tier, which bills no backup storage. Restore to a new account at a point in time, give the app identity its data role there (data-plane role assignments are not restored), then point `COSMOS_ENDPOINT` at it.
- **Drill, staging, 2026-11-01** (Azure activity log and Application Insights timestamps, one drill):

  | Step | Started (UTC) | Took |
  |---|---|---|
  | Point-in-time restore of `cosmos-trainyard-stg-swc` to `cosmos-trainyard-stg-drill`, restore point 11:36:56 | 11:39:51 | 10 min 19 s |
  | `07-restore-drill.sh`: Cosmos DB Built-in Data Contributor for `id-trainyard-app-stg` on the restored account | 12:02:18 | under 1 min |
  | `COSMOS_ENDPOINT` set on the Container App (new revision); first read from the restored account: the promotion lease, `GET .../checkpoints/docs/promotion` 200, then the timer's lease writes | 12:33:24 | 1 min 36 s |
  | `COSMOS_ENDPOINT` set back to the staging account; the drill account deleted | 12:38:21 | |

  **RTO:** 13 minutes of work (restore, role, switch), 55 minutes of wall clock from the restore request to the first read, because the owner ran the role script in between; target 4 h. **RPO:** the restore point is chosen to the second within the 7-day window; the restored account held the documents written before 11:36:56, including the promotion lease; target 24 h.
  **What the drill taught:** the app reports finished training runs once, using a marker kept in the lease document. A restored lease has an older marker, so the app sends `retrain_completed` and `model_evaluated` again for runs it had already reported. The workbook's KPI-1 tile counts each pipeline job once, and every KQL in this document does the same.
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

Azure Advisor, 2026-11-01: one recommendation on Trainyard resources, zone redundancy for `sttrainyardstgswc` (High availability). Not applied: it raises the storage price, and the workspace storage holds only rebuildable data (component code, the synthetic feed, models retrained from it, collected inputs). Like the single endpoint instance (ADR-005), no zone redundancy is a Reliability trade-off for cost: recovery is the rebuild from Bicep and the retraining described under *Backup and restore*.

The CI principal calls `/api/fleet/risk` with its own token, so it needs an app role: the sign-in app registration's `Reader` role allows applications and is granted to the staging CI principal, with version 2 access tokens (`08-load-test-reader.sh`, Learn: daemon client applications). `ModelApprover` stays users only. Load tests add their rows to the deployment's collected inputs, so they never run in the day before a monitor run that is meant to read real traffic.

Results: pending, phase 8.: about USD 52 a month at rest in staging and USD 61 in production, mostly the endpoint. Phase 8 compares it with Cost Management, per resource group.

## Load tests

`load-test.yml`, manual, against staging, before every production promotion. It runs Locust on the endpoint (with `aad_token`) and on `/api/fleet/risk`, which uses no language model:

| Scenario | Users | Duration | Gate |
|---|---|---|---|
| normal | 5 | 5 min | REQ-07 and REQ-08 |
| peak | 50 | 2 min | REQ-07 and REQ-08 |
| stress | ramp of 1 user a second up to 300 | until errors exceed 1 % or p95 exceeds 500 ms | none: it finds the breaking point |
| endurance | 10 | 30 min | REQ-07 and REQ-08 |
| chat | 2 | 2 min | none: it measures the time to first event |

The CI principal calls `/api/fleet/risk` with its own token, so it needs an app role: the sign-in app registration's `Reader` role allows applications and is granted to the staging CI principal, with version 2 access tokens (`08-load-test-reader.sh`, Learn: daemon client applications). `ModelApprover` stays users only. Load tests add their rows to the deployment's collected inputs, so they never run in the day before a monitor run that is meant to read real traffic.

Results: pending, phase 8. Each run's p50, p95, p99, requests per second, errors, peak endpoint CPU and memory, and app replicas go to its job summary and here, with the date.

## DORA metrics

Computed from the Actions runs, with `gh run list --workflow <name> --json conclusion,createdAt,headSha`:
- **Deployment frequency:** successful `release.yml` runs per month (production) and `deploy.yml` runs (staging).
- **Lead time for changes:** from a commit's merge to the `release.yml` run that deployed it.
- **Change failure rate:** releases followed by an image rollback or a `fix/` release, divided by releases.
- **Time to restore:** from a failed release, or an alert, to the run that restored service.

Measured in phase 9, over the project's own history.
