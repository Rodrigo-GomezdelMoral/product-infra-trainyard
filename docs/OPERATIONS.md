# Operations

How Trainyard is run, changed, recovered and paid for. State on 2026-11-10: staging is deployed since 2026-11-01 and production since `v1.0.0` (2026-11-03, 22:26 UTC); both run `v1.0.2`'s image, `sha256:343fa3a8d69d…`, and each endpoint serves one model (production: model 5 since 2026-11-10). Every measured figure below carries its date, window and number of cases.

## Environments

| | Staging | Production |
|---|---|---|
| Resource group | `rg-trainyard-stg-swc` | `rg-trainyard-prod-swc` |
| Deploys | every merge to `main` (`deploy.yml`), once `DEPLOY_STAGING` is `true` | a published `v*` release (`release.yml`), after the owner's approval |
| Container Apps environment | `cae-trainyard-env`, joined | `cae-trainyard-env`, Germany West Central, declared in this group (ADR-018) |
| Container App | `ca-trainyard-stg`, 0 to 2 replicas | `ca-trainyard-prod`, 0 to 3 replicas |
| Endpoint | `ep-trainyard-stg`, 1 × `Standard_DS1_v2` while a deployment exists | `ep-trainyard-prod`, the same |
| Monitor | on demand | daily at 03:15 UTC; disabled since 2026-11-04, because no run starts (REQ-04, ADR-010) |
| Budget | 60 in the billing currency (EUR), alerts at 80 % actual and 100 % forecast | 80 EUR, the same |

Each environment has its own identities, workspace, storage, Key Vault, Application Insights, Cosmos DB and Container App. Both apps share one Container Apps environment, `cae-trainyard-env`: the subscription allows 5 environments in all and 1 per region, so production declares it and staging joins it (ADR-018). Everything is in Sweden Central except that environment and the apps, in Germany West Central. Sweden Central allows one Container Apps environment per region, and another product uses it; West Europe refuses new resources from this subscription (ADR-017). Each call from the app to Cosmos DB, the endpoint or the workspace adds a 27 ms round trip. The shared base (registry, Foundry, Log Analytics, action group) belongs to the landing zone.

## Delivery

- **Switch.** `deploy.yml` runs only when the repository variable `DEPLOY_STAGING` is `true`. Phase 8 sets it once the sign-in app registration exists, so that no merge creates billed resources before the owner has seen the price.
- **One image per commit.** `deploy.yml` builds the image once, tagged `YYYYMMDD-main-<sha>`, and deploys it by digest. A re-run or a feed operation on the same commit reuses that image. The digest is recorded on the commit as the status `staging-image`.
- **Every deployment** (`.github/actions/ship`):
  1. reads the endpoint's live and mirrored traffic, by the endpoint's name: a failed deployment has no outputs, and an empty traffic would send no request to any deployment; only a missing endpoint reads as empty, and any other error stops the run, as does an endpoint whose creation failed (see *A failed endpoint*);
  2. runs `what-if`, then deploys `infra/main.bicep` with that traffic unchanged, and retries a failed deployment once after 10 minutes, Learn's bound for a new role assignment to take effect (ADR-006);
  3. checks `/healthz`;
  4. registers the four ML components with the image's version (the release tag in production).
- **The owner's identity scripts** live outside the repository and run once, in order: `00-github.sh` and `01-azure.sh` (setup); `02-shared-access.sh` (deployments and monitoring links in the shared group); `03-login.sh <env>` (the sign-in app registration; run it again after each deployment, because the callback URL follows the app's host name, which changes whenever the app or its environment is recreated); `04-staging-access.sh` (Monitoring Reader in the conditions, and `DEPLOY_STAGING`); `05-registry-link.sh` (`registries/read` and `/write` on the shared registry, which ARM checks at every PUT of a workspace that links it, ADR-007); `06-endpoint-providers.sh` (registers `Microsoft.PolicyInsights` and `Microsoft.Cdn`, and deletes the staging endpoint only if its creation failed); `10-environment.sh` (deletes `ca-trainyard-stg` and `cae-trainyard-stg-gwc`, creates `cae-trainyard-env` from `infra/modules/environment.bicep` with the values `main.bicep` passes, and grants the staging CI principal only `read` and `join/action` on it, ADR-018). The CI principals' roles and conditions change only through these scripts; the workflows create only the role assignments the Bicep declares, within those conditions.
- **Production** takes the digest that staging runs for the tag's commit. It is refused unless that commit has successful `load-test/normal`, `load-test/peak` and `load-test/endurance` statuses (REQ-07, REQ-08). The one exemption: when every path changed since the last release that reached production is under `web/`, `docs/` or `.github/`, or is a Markdown file, the staging image is still required but the load tests are not; the first release always needs them (ADR-019).
- **The first production deployment** needs two things the release itself does not create: the sign-in app registration with `AUTH_CLIENT_ID` on the production environment (`03-login.sh production`), and a first `fleet-feed` version in the production workspace. `v1.0.0`'s run 41727110829 (2026-11-03) failed twice for lack of each. Attempt 1 (22:02 UTC, 34 s) stopped at `main.bicepparam` with `BCP333`, an empty `AUTH_CLIENT_ID`: the production environment did not have it yet. Attempt 2 (22:06 to 22:15) deployed the infrastructure and the app (revision created 22:13:09), then stopped at `ml/pipeline.py:76`: "Asset fleet-feed does not exist in workspace mlw-trainyard-prod-swc". The dispatch 41729433631 on `v1.0.0` registered the feed (22:17 to 22:21), and attempt 3 passed (22:22 to 22:26). On a fresh environment, in order: `03-login.sh <env>`; push the tag and dispatch `release.yml` on it with `feed_days` (it deploys the infrastructure and the app and registers the feed, without training); publish the release on that tag, which trains and deploys; run `03-login.sh <env>` again for the callback URL.
- **`AUTH_CLIENT_ID`** is a secret of each GitHub environment from `v1.0.1`, so GitHub masks it in every log line (before, as a variable, run logs printed it). The variable stays as long as `v1.0.0` is a rollback target: a dispatch on a tag runs that tag's workflow file, and `v1.0.0`'s reads the variable.
- **Fleet feed operations** (ADR-012) are `workflow_dispatch` inputs of `deploy.yml` and `release.yml`: `feed_days` (days from 2025-11-01) and `firmware_b_from` (the drift scenario). Each one registers a new `fleet-feed` version, logged in the Actions history. Never from a laptop. The staging drift scenario uses `feed_days=365` and `firmware_b_from=2026-05-01`, run on 2026-11-01. A local rehearsal with the same code chose that date: with the shift from May, a retrained model keeps recall 0.90 and Series B recall 0.71 on the new holdout while the current model drops to 0.84 and 0.14, so the gate registers the challenger and the comparison favours it; with the shift from August, too little of it reaches the training window and the challenger fails the gate on Series B (0.14).
- **Next runtime release** (it needs the release load tests, ADR-019), from the validation of 2026-11-04: the Application Insights daily cap and sampling in `infra/modules/ml.bicep`; a digest check in `load-test.yml`; `ml/environment/Dockerfile` pinned by digest instead of the tag `20261018.v1` (Dependabot #6) and numpy 2.4.6 (#3); the endpoint's telemetry without an instrumentation key and a cloud role name; the chat's first-event measurement (ADR-014).
- **Urgent patches** go through a `fix/` branch, the same CI and a patch release. They are pre-approved: the owner's approval of the production environment is the change approval.

## Model promotion and rollback

- **Promotion** happens in the chat, by a `ModelApprover`: shadow at 20 % mirrored traffic, canary at 10 % with an automatic health check, then 100 % (ADR-009).
- **Model rollback:** one step inside the window, back to the previous deployment. After the window, promote the previous model version through the same workflow.
- **Never run blue/green in both environments at once.** The DSv2 quota (6 cores) holds staging, production and one pair (ADR-005).
- **Do not merge while a promotion step is running.** A deployment reads the traffic seconds before it applies it, and would undo a change made in between (ADR-004).

## Image rollback

1. Staging: run `deploy.yml` with the earlier image's `digest`.
2. Production: run `release.yml` on the earlier `v*` tag. The production environment accepts only `v*` tags, with the owner's approval. A dispatch never retrains. On `v1.0.0`, `verify` finds no earlier promoted release and requires that commit's load-test statuses, which exist.

The app runs in single revision mode, so each step is a new revision through a full deployment, about 4 minutes; there is no faster path through revision activation. `v*` tags cannot be moved or deleted (ruleset `protect-release-tags`), so the tag a rollback names is the commit that was released.

**Drill, 2026-11-04** (GitHub Actions run times, one drill per environment, from `v1.0.1` back to `v1.0.0` and forward again):

| Step | Run | Started (UTC) | Took |
|---|---|---|---|
| Staging to `v1.0.0`'s image (`deploy.yml`, `digest`) | 41908736776 | 20:39:53 | 4 min 20 s |
| Staging back to `v1.0.1`'s image | 41909446245 | 20:44:23 | 3 min 30 s |
| Production to `v1.0.0` (`release.yml` on the tag, the owner's approval included) | 41911690911 | 20:58:47 | 12 min 29 s |
| Production back to `v1.0.1` (the same, approval included) | 41913727279 | 21:11:24 | 5 min 3 s |

Both apps ended on `v1.0.1`'s digest, and each endpoint kept its model: an image rollback leaves the model's traffic as it was. The production rollback is the time to approve plus about 4 minutes of deployment.

## Alerts and who receives them

Every alert goes to the shared action group `ag-aiplatform-shared`; the budget alerts go to `ALERT_EMAIL_ADDRESS`. The owner receives both.

| Alert | Fires when | Runbook |
|---|---|---|
| `alert-trainyard-<env>-endpoint-5xx` | any 5xx on the endpoint over 15 minutes | console log (`AmlOnlineEndpointConsoleLog`) → roll traffic back if a canary is live |
| `alert-trainyard-<env>-endpoint-p95` | `RequestLatency_P95` above 400 ms for 15 minutes | workbook SLA tiles → endpoint metrics by deployment |
| `alert-trainyard-<env>-app-5xx` | more than 5 server errors from the app in 15 minutes | App Insights failures → `/healthz` → the dependency named in the error |
| `alert-trainyard-<env>-run-failed` | a failed run in the workspace (`AmlRunStatusChangedEvent`, `Status == "Failed"`, split by `RootRunId`: the table has no experiment name), so a pipeline failure or a monitor breach. **Blind spot:** a run that stays Queued or Running never fails and never fires it (ADR-010) | workbook → `model_status` in the chat → retrain → promote |
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

### The stuck monitor run, 2026-11-04

Production's first monitor run started at 03:15 UTC and never started its Spark steps: the service submitted the four `model_data_collector_preprocessor` steps on runtime 3.4 while the schedule reads 3.5, and they stayed Queued with no charged core-seconds, the defect ADR-010 records in staging. No alert fired (the blind spot above). After 11 hours the owner cancelled the run and disabled the schedule (`22-monitor-stop.sh`). REQ-04's monitor is NOT VERIFIED, a documented limitation. The promotion's `watch()` re-creates the schedule enabled whenever a model goes to 100 % or traffic goes back after a rollback, so `22-monitor-stop.sh` runs again after every production promotion or rollback.

## Backup and restore

- **Cosmos DB:** continuous backup, 7-day tier, which bills no backup storage. Restore to a new account at a point in time, give the app identity its data role there (data-plane role assignments are not restored), then point `COSMOS_ENDPOINT` at it.
- **Drill, staging, 2026-11-01** (Azure activity log and Application Insights timestamps, one drill):

  | Step | Started (UTC) | Took |
  |---|---|---|
  | Point-in-time restore of `cosmos-trainyard-stg-swc` to `cosmos-trainyard-stg-drill`, restore point 11:36:56 | 11:39:51 | 10 min 19 s |
  | `07-restore-drill.sh`: Cosmos DB Built-in Data Contributor for `id-trainyard-app-stg` on the restored account | 12:02:18 | under 1 min |
  | `COSMOS_ENDPOINT` set on the Container App (new revision); first read from the restored account: the promotion lease, `GET .../checkpoints/docs/promotion` 200, then the timer's lease writes | 12:33:24 | 1 min 36 s |
  | `COSMOS_ENDPOINT` set back to the staging account; the drill account deleted | 12:38:21 | |

  **RTO:** 13 minutes of work (restore, role, switch), 55 minutes of wall clock from the restore request to the first read, because the owner ran the role script in between; target 4 h. **RPO:** the restore point is chosen to the second within the 7-day window; the restored account held the documents written before 11:36:56, including the promotion lease; target 24 h. Learn (*Continuous backup with point-in-time restore*, 2026-07-13): in a steady state every mutation is backed up asynchronously within 100 seconds, so the achievable RPO is about 100 seconds, far inside the target. Production is not rehearsed: by design no human holds a data role there, and the staging drill used the same Bicep, tier and procedure.
  **What the drill taught:** the app reports finished training runs once, using a marker kept in the lease document. A restored lease has an older marker, so the app sends `retrain_completed` and `model_evaluated` again for runs it had already reported. The workbook's KPI-1 tile counts each pipeline job once, and every KQL in this document does the same.
- **Models and data assets** are immutable versions in each workspace. Storage has blob and container soft delete for 7 days.
- **The workspace** is rebuilt from the Bicep and retrained from its data assets.

## Switching on and off

| To | Do |
|---|---|
| Stop the hourly cost of an environment | delete its endpoint deployments; the endpoint, models and data stay |
| Stop the daily monitor | `22-monitor-stop.sh` (cancels unfinished runs, disables the production `MonitorSchedule`); again after every production promotion or rollback |
| Stop deployments to staging | set `DEPLOY_STAGING` to anything but `true` |
| Switch staging on again | run `deploy.yml`, then promote a model from the chat |

Container Apps, the workspace, Cosmos DB serverless and serverless compute cost nothing while idle. **Staging ends every phase at zero,** except the endpoint, whose cost the phase close states.

## Cost per environment

Azure Advisor, 2026-11-01: one recommendation on Trainyard resources, zone redundancy for `sttrainyardstgswc` (High availability). Not applied: it raises the storage price, and the workspace storage holds only rebuildable data (component code, the synthetic feed, models retrained from it, collected inputs). Like the single endpoint instance (ADR-005), no zone redundancy is a Reliability trade-off for cost: recovery is the rebuild from Bicep and the retraining described under *Backup and restore*. Read again on 2026-11-03 at 20:45 UTC: the same storage recommendation, and zone redundancy for `cae-trainyard-stg-gwc`, a Container Apps environment that no longer exists (staging joined `cae-trainyard-env`, ADR-018); Advisor still lists it from its last assessment, and nothing applies.

Read again on 2026-11-04: the same two staging rows, nothing for production.

Estimate: about USD 52 a month at rest in staging and USD 61 in production, mostly the endpoint. Measured month to date on 2026-11-04 (Cost Management, EUR): staging 6.61, production 0.52; the meters, including two the estimate missed (IP Addresses and the drill's point-in-time restore), are in `cost.md`.

**Telemetry settings.** Both Application Insights components keep the defaults: a daily cap of 100 GB, no ingestion sampling, IP masking on; the shared workspace keeps `AppRequests` 90 days. The build prompt asked for a daily cap, sampling and 30-day retention. Volumes are tiny, so nothing is billed today; the cap and sampling go into `infra/modules/ml.bicep` in the next runtime release (an `infra/` change needs the load tests, ADR-019), and retention belongs to the shared workspace. The endpoint deployments set `app_insights_enabled` with an instrumentation key, but local auth is off on Application Insights, so no endpoint telemetry arrives there; the SLIs read the endpoint's logs in Log Analytics. No cloud role name is set, so every item carries `unknown_service:python3.12`.

## Load tests

`load-test.yml`, manual, against staging, before every production promotion. Locust drives the load on the endpoint (with `aad_token`) and on `/api/fleet/risk`, which uses no language model. REQ-07 and REQ-08 are judged where they are defined: on the endpoint's `AmlOnlineEndpointTrafficLog` for the run's window, every request except the app's agreement probes, failed (`5xx`, `408`, `429`) at most 0.5 % and p95 of `TotalDurationMs` under 500 ms. Locust's own times include the runner's network path to Sweden Central: on 2026-11-03 its score median was 460 ms against the endpoint's 100–130 ms, so they are reported and do not gate. A `424` (`too_few_model_instance`, under 10 ms) is outside the SLI's failure definition; Locust counts it as an error. The workflow signs in again after the scenario, because the OIDC client assertion of `azure/login` expires after 5 minutes, and it judges only once the endpoint's log for the window has fully arrived: the window's last minute is there and the count holds for a minute, up to 20 minutes; otherwise the job summary says the read is partial and the gate fails.

| Scenario | Users | Duration | Gate |
|---|---|---|---|
| normal | 5 | 5 min | REQ-07 and REQ-08 |
| peak | 50, spawned 5 a second, one request every 10 s each, an even 5 a second at the endpoint (ADR-005) | 2 min | REQ-07 and REQ-08 |
| stress | ramp of 1 user a second up to 300 | until Locust sees errors above 1 %; the job summary lists the endpoint's p95 per minute, where the 500 ms break is read | none: it finds the breaking point |
| endurance | 10 | 30 min | REQ-07 and REQ-08 |
| chat | 2 | 2 min | none: it measures the time to first event |

The CI principal calls `/api/fleet/risk` with its own token, so it needs an app role: the sign-in app registration's `Reader` role allows applications and is granted to the staging CI principal, with version 2 access tokens (`08-load-test-reader.sh`, Learn: daemon client applications). `ModelApprover` stays users only. Load tests add their rows to the deployment's collected inputs, so they never run in the day before a monitor run that is meant to read real traffic.

Each run's p50, p95, p99, requests per second, errors, peak endpoint CPU and memory, and app replicas go to its job summary and here, with the date. The rows up to 20:07 on 2026-11-03 are history, on earlier commits; the release commit of `v1.0.0` is `0246d04`, whose three gating runs close the table.

**Known gap (validation, 2026-11-04).** `load-test.yml` writes `load-test/<scenario>` on the dispatching commit without checking that staging runs that commit's digest, and it does not print the digest. For `0246d04` the tested image is `sha256:6ac91b788415…` by timing: staging's only revision, `--0000008`, was created at 21:13:21 and the tests ran from 21:16 to 21:59. In those runs the endpoint's CPU and memory reads came back empty and the app's replicas never passed 1. A digest check is planned for the next runtime release.

| Date | Scenario | Result | Causes and changes |
|---|---|---|---|
| 2026-11-02 | normal, during a shadow (`green` mirrored at 20 %) | **failed.** Score: 629 requests, 4 × `429`, p95 470 ms. Fleet risk: 170 requests, 14 × `500`, 2 × `429`, p95 1.1 s, maximum 34 s | The endpoint's `429`s are `max_concurrent_requests_exceeded`: one request at a time per instance, the default; now `WORKER_COUNT` 2 and 4 concurrent requests (ADR-005). The fleet's 2 × `429` are those same rejections, passed on as `429` with `Retry-After`. The 14 × `500` came from the sign-in sidecar, which could not forward while the app container was killed twice (exit 137) within 20 s of a scale from zero; every first request downloaded and built the year-long feed at once, at about 87 % of the 1 GiB limit afterwards. Now one build at a time, and 0.75 vCPU with 1.5 GiB. The mirror loads only `green`, not `blue`. To be run again |
| 2026-11-03 08:27 | normal, before the shadow, only `blue` (model 2, one worker) | **failed.** Score: 641 requests, 6 × `429`, 1 × `424`, p95 470 ms in Locust. Fleet risk: 202 requests, 2 × `429`, no `500`, p95 3.1 s | `blue` still ran the one-worker setting: the `429`s are its rejections. No `500` after the memory fix. To be run again on one deployment with the new setting |
| 2026-11-03 08:38 | normal, during the shadow (`green`, model 4, two workers, mirrored at 20 %) | **failed.** Score: 638 requests, 5 × `429`, p95 490 ms in Locust. Fleet risk: 225 requests, 3 × `429`, p95 910 ms | Every `429` from `blue`. To be run again |
| 2026-11-03 09:24 | endurance, through the canary (`green` 10 %) and the promotion (`green` 100 % from 09:30) | **failed on REQ-07.** Endpoint: 9,187 requests, 73 failed (0.79 %), p95 361 ms. Locust: score 5,996 requests, p95 700 ms; fleet risk 3,279, 19 × `429`, 3 × `503`, p95 1.2 s | All 73 failures are `blue`'s `429`s during the canary; `green` had none in 7,468 requests from 09:31 to 09:54, p95 375 ms, which meets both SLAs. The canary split was right: `green` took 11.7 % of 1,660 requests from 09:24 to 09:29 (a 10 % weight). The fleet's 3 × `503` are the endpoint's `424 too_few_model_instance` passed on by the app. Fleet risk p95 is the app's own path (a workspace lookup of the feed version, the scoring call and the runner's network); it carries no SLA |
| 2026-11-03 10:08 | peak, only `green` (model 4, two workers, four concurrent requests) | **failed on REQ-07 and REQ-08.** Endpoint: 2,558 requests, 1,690 × `429 too_many_pending_request` (66 %), the 200s at p50 about 1 s and p95 about 1.25 s. Locust: score 1,882, fleet risk 661 | Capacity: one DS1_v2 completes about 7 requests of 40 rows a second; 50 users offer about 26 (25 scoring users at about one a second and 25 fleet users, each of whose requests scores once). Below that, at about 5 a second, p95 is 375 ms with no failures. More instances do not fit the DSv2 quota (6 cores for staging, production and one blue/green pair). Decided on 2026-11-03: one instance, and REQ-07 and REQ-08 hold up to 5 requests a second of 40 rows; peak is now 50 users at one request every 10 s (ADR-005). To be run again |
| 2026-11-03 18:10 | normal, during the shadow of model 4 (`green` mirrored at 20 % from 18:11, `blue` model 2 live) | **passed** | `green` answered its 147 mirrored requests with 0 failures, p95 about 105 ms (console log, ADR-009) |
| 2026-11-03 18:44 | normal, during the canary (`green` 10 %) | **failed on REQ-07.** Locust: 11 of 816 failed. Endpoint: every failure a `429` of `blue` (model 2, the old one-worker setting), 12 in the run; `green` answered 96 of 96 | The canary split worked and `green` had no failure; *Promote to 100 %* at 18:59 and *Close window* before 19:09 left `green` (model 4) as the only deployment |
| 2026-11-03 19:09 | normal, `6d091cf`, only `green` | **passed.** Endpoint: 859 requests in 5 min (2.9 a second), 0 failed, p50 102 ms, p95 238 ms | |
| 2026-11-03 19:15 | peak, `6d091cf` | **failed on REQ-07 and REQ-08.** Endpoint: 600 requests in 114 s (5.3 a second), 97 × `429` (16 %), p50 684 ms, p95 992 ms. Locust: score 469, 75 × `429` | Bunching, not capacity: 50 users spawned 10 a second with `constant_pacing(10)` kept their requests in step, bursts of about 10 a second in each 10 s cycle. Peak now spawns 5 users a second, an even 5 a second (ADR-005). To be run again by the release gate |
| 2026-11-03 19:19 | endurance, `6d091cf` | **met REQ-07 and REQ-08 at the endpoint; the workflow failed.** Endpoint, 19:19:30 to 19:49:40: 9,680 requests, 5.38 a second, 0 failed, p50 156 ms, p95 399 ms | The judging step ran 30 minutes after `azure/login`, whose OIDC client assertion expires after 5 minutes (`AADSTS700024`), so it read nothing. `load-test.yml` now signs in again after the scenario. To be run again by the release gate |
| 2026-11-03 20:05 | stress, `6d091cf` | **breaking point at about 35 users.** Locust: 2 of 187 scoring requests `429` (1.07 %). Endpoint, 20:06:10 to 20:06:59: 214 requests, 3 × `429`, p95 820 ms; by 10 s, 4.2 a second at p95 314 ms, 7.1 at 649 ms, 7.4 at 847 ms with the `429`s | The latency SLA breaks at about 7 a second (ADR-005). The run's own endpoint read caught 37 rows, before ingestion finished; `load-test.yml` now waits until the window's last minute has arrived and the count holds, and says when it reads partially |
| 2026-11-03 20:07 | chat, `6d091cf` | **the workflow failed on a test defect;** Locust's 30 chat entries had 0 failures, p95 about 470 ms; Application Insights, 20:00 to 20:15: 26 chat turns, 0 errors, p95 6.2 s for the whole streamed turn | Locust requires `catch_response=True` on a streamed request used in a `with` block (`LocustError`); `ChatUser` now passes it and marks each answer as a success or a failure itself |
| 2026-11-03 21:16 | normal, `0246d04` (run 41720361703), only `green` | **passed.** Endpoint: 852 requests in 5 min (2.8 a second), 0 failed, p50 101 ms, p95 226 ms, p99 291 ms | the release gate's `load-test/normal` |
| 2026-11-03 21:24 | peak, `0246d04` (run 41721489186) | **passed.** Endpoint: 600 requests in about 2 min (5 a second), 0 failed, p50 224 ms, p95 429 ms, p99 524 ms | Spawning 5 users a second removed the bunching: 0 `429` against 97 on `6d091cf`. p95 meets the 500 ms SLA and misses the 400 ms SLO by 29 ms |
| 2026-11-03 21:28 | endurance, `0246d04` (run 41722116185) | **passed.** Endpoint: 9,676 requests in 30 min (5.38 a second), 0 failed, p50 152 ms, p95 389 ms, p99 510 ms. Locust: 3 × `503` on fleet risk in 9,675 | Both SLAs and the latency SLO met at the load bound. The three `503`s are on the app's path, in Locust only: the endpoint's log has no failure in the window |
| 2026-11-10 10:06 | normal, `7301e3b` (run 42796157575), for the demo recording | **passed.** Endpoint: 846 requests in 5 min (2.82 a second), 0 failed, p50 102 ms, p95 216 ms, p99 284 ms; at most 1 app replica | The p50 and p99 of the four rows from 2026-11-03 21:16 on were read on 2026-11-10 from `AmlOnlineEndpointTrafficLog` with the workflow's filter, over each run's window |

## KPIs and SLOs, measured

Staging, read on 2026-11-03 at 20:40 UTC at the close of phase 8, after the rollback drill, the second promotion of model 4 and the release load tests, over its whole life since 2026-11-01, with the workbook's queries (filtered to the staging Application Insights and endpoint in the shared workspace). Staging is a test bed: its traffic is mostly load tests, including two that searched for the limit on purpose. Production's figures follow the table.

| | Value | Window and cases | Target |
|---|---|---|---|
| REQ-07 availability | 100 % in the endurance run, at 5.38 requests a second; 99.12 % with only `green` serving (the 97 bunched `429`s of the first peak run and the 3 `429`s of stress); 93.09 % over the whole life, which holds the diagnostic peak at 26 a second (1,690 × `429`) and `blue`'s one-worker rejections | 9,680 requests (19:19:30 to 19:49:40); 11,370 (18:59 to 20:40); 27,508 (2026-11-01 to 2026-11-03) | ≥ 99.5 % |
| REQ-08 p95 latency | 399 ms in the endurance run; per day 527 ms on 2026-11-01, 179 ms on 2026-11-02, 630 ms on 2026-11-03 (both peak runs) | 9,680 requests; 5, 815 and 26,688 requests | < 500 ms |
| Chat errors and duration | 0 errors; p95 12.3 s for the whole streamed turn | 54 chat turns | errors < 1 %; the time to first event is not instrumented, so the chat is reported on the whole turn (ADR-014) |
| KPI-1 model cycle time | median 7.5 min, worst 8.7 min from the `retrain_completed` events' `duration_minutes`; median 7.6 min, worst 8.8 min on the jobs' own creation-to-end timestamps in the run history, the definition in `PRODUCT.md` | 6 training runs | ≤ 120 min |
| KPI-2 drift-to-production lead time | not measurable in staging: no monitor run has completed (serverless Spark does not start in this subscription, ADR-010), so no promotion followed a breach | 3 promotions | ≤ 24 h |
| KPI-3 predictive quality | recall 0.8406 at precision 0.8657 (`training-20261103163556`) | latest matured window | recall ≥ 0.80 at precision ≥ 0.60 |
| KPI-4 promotion failure rate | 33 %: the one rollback is the drill REQ-05 asks for (model 4, 13:26 UTC), not a failed promotion | 3 promotions, 1 rollback | ≤ 15 % |
| KPI-5 planner satisfaction | 100 % | 1 vote | ≥ 80 % |

Production, read on 2026-11-04 at 20:05 UTC (validation), from its creation on 2026-11-03 at 22:26 UTC. It has no planners: its use is the release's training run, the owner's approval of the first model and the walk-through below.

| | Value | Window and cases | Target |
|---|---|---|---|
| REQ-07 and REQ-08 | 100 %; p95 119 ms on `blue` (model 1) and 112 ms on `green` (model 2) | 1,964 endpoint requests in `AmlOnlineEndpointTrafficLog`, 2026-11-04 16:20 to 20:05 UTC, the owner's walk-through traffic (mirrored requests are not in this table) | ≥ 99.5 %; p95 < 500 ms |
| App requests and chat | 616 app requests (22:13 to 23:02), 0 failed; 2 chat turns, p95 4.1 s for the whole streamed turn | 2026-11-03 | errors < 1 % |
| KPI-1 model cycle time | 7.1 min from the event; 7.3 min on the job's timestamps (`training-20261103222555`) | 1 training run, started by the release; model 2 (`training-20261104162614`) registered about 8 min after its approval on 2026-11-04 | ≤ 120 min |
| KPI-2 drift-to-production lead time | not measurable: no monitor run has completed (ADR-010) | 1 promotion | ≤ 24 h |
| KPI-3 predictive quality | recall 0.8986 at precision 0.8732 | 1 matured window | recall ≥ 0.80 at precision ≥ 0.60 |
| KPI-4 promotion failure rate | 50 %: the one rollback is REQ-05's drill (model 2, 17:38 UTC), not a failed promotion | 2 promotions of model 2, 1 rollback (the first model's approval is not a promotion) | ≤ 15 % |
| KPI-5 planner satisfaction | 100 % | 1 vote, the owner's, in the walk-through | ≥ 80 % |

Production, read again on 2026-11-10 after the demo recording, with the workbook's queries. Its use is now the three releases' training runs, the conversations seeded before the recording, and the owner's and a `Reader`'s recorded walk-through below.

| | Value | Window and cases | Target |
|---|---|---|---|
| REQ-07 and REQ-08 | 100 %; p95 117 ms | 3,043 endpoint requests, 0 failed, in the 30 days to 2026-11-10 (16 of them the shadow's agreement checks) | ≥ 99.5 %; p95 < 500 ms |
| KPI-1 model cycle time | median 7.1 min (7.1, 7.6, 7.1, 7.8 and 3.5 min) | 5 training runs: 3 started by the releases, 2 approved in the chat (2026-11-04 and 2026-11-10) | ≤ 120 min |
| KPI-2 drift-to-production lead time | not measurable: no monitor run has completed (ADR-010) | 3 promotions | ≤ 24 h |
| KPI-3 predictive quality | recall 0.8986 at precision 0.8732 | the serving models on the same holdout: models 2 and 5 both show 89.9 % and 87.3 % on the shadow card | recall ≥ 0.80 at precision ≥ 0.60 |
| KPI-4 promotion failure rate | 33 %: the one rollback is REQ-05's drill of 2026-11-04, not a failed promotion | 3 promotions (model 2 twice, model 5 once), 1 rollback | ≤ 15 % |
| KPI-5 planner satisfaction | 90 % | 10 votes, from the seeded conversations and the owner's: synthetic use | ≥ 80 % |

### Production walk-through, 2026-11-04

Recorded with `ops/record.py` as the published demo (`web/src/demo/runs`); times in UTC from the recorder's log and the endpoint.

| Step | Result |
|---|---|
| Fleet feed with firmware-b (`release.yml` dispatch, owner's approval) | success in 5 min, 15:50; `fleet-feed` `20261104154812` |
| Run 1, the week's inspection list (owner) | EMU 2402 first at 99 %, budget 6; model 1 |
| Run 2, a unit and its lineage | EMU 2417 at 0 % (threshold 15 %), not flagged; `training-20261103222555`, `fleet-feed` `20261103222125`, tag `v1.0.0` (REQ-01) |
| Run 3, drift | signals watched; "no monitor run has completed", nothing reported as breached (REQ-04 NOT VERIFIED) |
| Run 4, retraining approved in the chat | `training-20261104162614` at 16:26; model 2 registered and gated at 16:36 (REQ-02) |
| Model rollback drill (REQ-05) | model 2 in shadow from 16:49 (20 % mirrored), canary at 10 % at 17:36; Roll back at 17:38: model 1 back at 100 % in 3 s, the challenger removed in 269 s |
| Run 5, shadow, canary and promotion | model 2's second promotion: shadow card 34 mirrored requests, 0 failed, p95 111 ms; canary at 10 % from 19:38, ready; 100 % and window closed at 19:54, model 1 removed |
| Run 7, a `Reader` asking to promote | refused, no tool call offered (REQ-05, elevation of privilege) |
| Feedback and deletion | one thumbs up at 20:00 (REQ-09); one conversation deleted at 20:00 (REQ-10) |
| Monitor schedule | disabled again at 20:00: each promotion re-creates it enabled (ADR-010) |

The shadow card keeps the readiness it was asked with; the app measures the shadow again only when the owner answers it, so a card that says "not ready" after 30 minutes moves on at the next Start canary. Run 5 begins with "Another promotion is in progress": the recorder was restarted after the first shadow had started, and recorded that promotion from its shadow card on.

### Production walk-through, 2026-11-10

Recorded live for the demo video, as the owner and as a `Reader`, after the release of `v1.0.2` (10:37 UTC).

| Step | Result |
|---|---|
| Load test in staging | normal on `7301e3b`: 846 requests, 0 failed, p95 216 ms (*Load tests*) |
| The week's inspection list | EMU 2402 (series A) first at 100 %, budget 6; model 2 (REQ-06) |
| A unit and its lineage | EMU 2402 flagged (threshold 35 %); model 2, `training-20261104162614`, `fleet-feed` `20261104154812`, tag `v1.0.0` (REQ-01) |
| A `Reader` asking to promote | refused; the chat gave the serving model's lineage instead (REQ-05) |
| Drift | "drift cannot be determined": no monitor run has completed (REQ-04 NOT VERIFIED) |
| Retraining approved in the chat | `training-20261110105947` on `fleet-feed` `20261104154812`; model 5 registered (REQ-02) |
| Shadow of model 5 | 291 requests on model 2 and 60 mirrored to model 5, 0 failed, p95 112 and 100 ms, 100 % agreement; recall 89.9 % and precision 87.3 % for both on the same holdout (REQ-03) |
| Canary at 10 % | 15 health checks in 15.4 minutes: 11 requests, 0 failed, p95 113 ms; healthy and ready for 100 % |
| Promotion and window | model 5 at 100 % on `blue`; Close window removed model 2 (REQ-05) |
| Feedback | a thumbs up, counted in the workbook's KPI-5 (REQ-09) |
| Monitor schedule | still disabled after the promotion (read at the end of the day) |

## DORA metrics

Computed from the Actions runs, with `gh run list --workflow <name> --json conclusion,createdAt,headSha`:
- **Deployment frequency:** successful `release.yml` runs per month (production) and `deploy.yml` runs (staging).
- **Lead time for changes:** from a commit's merge to the `release.yml` run that deployed it.
- **Change failure rate:** releases followed by an image rollback or a `fix/` release, divided by releases.
- **Time to restore:** from a failed release, or an alert, to the run that restored service.

Measured in phase 9 on 2026-11-03 at 20:45 UTC, over the project's own history (`deploy.yml` from 2026-10-31 21:44 to 2026-11-03 16:29 UTC, 20 runs; 23 merged pull requests). Production's column is read on 2026-11-04 from `v1.0.0` (PR #30 merged 21:09:32 UTC, tag published 22:01:51, production deployed 22:26:04); staging's, from the same definitions:

| Metric | Staging | Production |
|---|---|---|
| Deployment frequency | 16 successful `deploy.yml` runs in 2.8 days, about 6 a day (13 on merges, 3 dispatched) | 1 release in 1 day (`v1.0.0`, 2026-11-03) |
| Lead time for changes | median 5.9 min, worst 7.3 min, from a merge to its successful staging deployment (12 merges that deployed) | 77 min from the merge to production; 24 min from the tag, through two failed attempts (see *Delivery*) |
| Change failure rate | 19 %: 3 of 16 deployments on merge failed | 0 of 1: no image rollback or fix release; the two failed attempts came before the first deployment and changed nothing that served users |
| Time to restore | median 1.6 h (12.3 h, 1.6 h and 0.5 h) from a failed deployment to the next successful one | no restore needed yet |

Production, read again on 2026-11-10 over its three releases, with the same definitions:

| Metric | Production |
|---|---|
| Deployment frequency | 3 releases in 7 days: `v1.0.0` (2026-11-03), `v1.0.1` (2026-11-04) and `v1.0.2` (2026-11-10) |
| Lead time for changes | 77 min for `v1.0.0` and 18 min for `v1.0.1` (PR #34 merged 20:17:53, deployed 20:35:24 UTC); `v1.0.2` was held on purpose for the demo recording, 5.5 days after its merge, and deployed 7 min after its tag (10:37:46 to 10:44:34 UTC) |
| Change failure rate | 0 of 3: no fix release; the one image rollback, on 2026-11-04, was the drill in *Image rollback* |
| Time to restore | none needed; the drill went back to `v1.0.0` in 12 min 29 s |
