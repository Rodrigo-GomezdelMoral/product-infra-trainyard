# CLAUDE.md · working agreement

`product-infra-trainyard` is **Trainyard**: 7-day failure risk for a fleet of 40 electric multiple units, with a governed model lifecycle and rollback. A maintenance planner asks which trains to inspect this week and why; a model owner retrains, compares, promotes and rolls back the model in the same chat. A staff engineer and a product manager read this repository for ten minutes and must conclude that the author ships products, not demos: a customer with a measurable problem, requirements with acceptance criteria, KPIs measured in production, a safe way to change the model, and nothing more than that needs. The product is described in `docs/PRODUCT.md`.

The governing rule:

> **If Azure Machine Learning, Container Apps or Azure Monitor already does it, configure it. The code that remains expresses a modelling, product or business decision.**

Re-read this file at the start of every phase, and reason the plan before touching code: which `REQ` the phase closes and how each one will be shown.

## Process

- **Trunk-based.** One short branch per phase, with the name in `Phases`, created from an up-to-date `main`. No environment branches.
- **Never** `git add`, `git commit`, `git push`, `gh pr create`, merges, force pushes, `--amend` of anything published, or branch deletion. The owner commits, pushes and opens the pull request with the phase's publish script, which lives outside the repository in `../_scripts/product-infra-trainyard/`. No `Co-Authored-By` and no tool attribution anywhere: the owner is the only author.
- **Identity is the owner's.** Roles, federated credentials and app registrations go in `../_scripts/product-infra-trainyard/<nn>-<what>.sh`, and the phase stops.
- **Close every phase in this order:**
  1. `ruff check .`, `ruff format --check .`, `mypy`, `pytest` (which runs `tests/test_budget.py`) and the phase's own checks;
  2. conformance with the phase's rows of the `Guidance map` below and with the Well-Architected service guide of every resource it creates;
  3. the block below, with real counts;
  4. `../_scripts/product-infra-trainyard/publish-<branch without feature/>.sh`: only the phase's paths, the commit in English, the pull request to `main` with the phase summary;
  5. `git status --short` and the script's path; then stop until the owner says "continue".

```
── PHASE n COMPLETE ──
Files: n/100   Python: app n/1150 · ml n/450 · ops n/100   Tests: n/700   Bicep: n/490   TypeScript: n/800   Comments: n/5
Verified: ruff ✓  mypy ✓  pytest ✓  budget ✓  <phase checks>
Requirements: REQ-nn (test <name>; live <what was seen>) · …
Guidance: <syllabus sections> · <Well-Architected codes>
Publish: ../_scripts/product-infra-trainyard/publish-<branch>.sh
```

- **Verify before writing.** Every SDK class, Bicep API version and CLI parameter is checked against Microsoft Learn or the installed package before it is written. Anything marked NOT VERIFIED is settled by the phase that first uses it, and the result goes in its ADR.
- **Say only what was checked**, and say which state it is in: implemented, tested, deployed to staging, deployed to production, or pending.
- **Every non-trivial decision** names its alternatives and why one was chosen; a departure from the syllabus or Well-Architected is fixed or justified in an ADR.

## Non-negotiable constraints

1. **No identifiers.** No GUID, e-mail, `*.azurecontainerapps.io`, `*.services.ai.azure.com` or other Azure host, public IP or `C:\Users` path in files, commits or docs. Shared-base names arrive as GitHub variables; everything else is derived in Bicep. `test_no_identifiers` scans every file in the repository; built-in role definition ids, when the Bicep needs them, are allowlisted there one by one.
2. **Zero secrets.** Entra ID everywhere, `DefaultAzureCredential`, local authentication disabled wherever the service allows it, `aad_token` on the endpoint, OIDC for GitHub Actions. The only Key Vault is the one the Azure Machine Learning workspace requires.
3. **Budgets**, enforced by `tests/test_budget.py`. Lines are non-empty lines.

   | Budget | What counts | Limit |
   |---|---|---|
   | Files | every file outside `docs/` and `eval/datasets/` | 100 |
   | `ml/` files | every file under `ml/` (ADR-003) | 10 |
   | Python app | `.py` under `app/`, `eval/` and `load/` | 1,150 |
   | Python ml | `.py` under `ml/` | 450 |
   | Python ops | `.py` under `ops/` | 100 |
   | Tests | every other `.py`: `tests/` (ADR-003) | 850 |
   | Bicep | `.bicep` and `.bicepparam` | 490 |
   | TypeScript | `.ts` and `.tsx` | 800 |
   | Comments | `#` comments in Python | 5 |

   The why goes in ADRs and the README, not in comments. The only other `#` in the repository are the release-tag annotations next to SHA-pinned actions, which Dependabot maintains. Every block that exists only because this is a product (sign-in, KPI events, feedback, deletion) cites its `REQ`.
4. **No defensive clutter.** No bare `except` and no `except Exception`; ruff `BLE` and the budget test both enforce it. Resilience comes from the platform: SDK timeouts and retries, a clear answer to a `429` or a dependency that is down, health probes, a pinned model version.
5. **Pinned.** Exact `==` pins in every `requirements*.txt`; GitHub Actions pinned to a full commit SHA. Dependabot covers `pip`, `github-actions` and `docker` (`ml/environment`, phase 3); phase 6 adds `npm` with `web/`. Dependabot does not read `ml/environment/conda.yaml`: `test_environment_pins_match_the_laptop` fails until a bump of a shared package is copied there in the same pull request.
6. **No notebook is part of the system.**
7. **Agents and workflows** live in code, with Agent Framework, self-hosted in Container Apps. Never an agent or workflow defined in Foundry.
8. **Synthetic data only.** MetroPT-3 is cited as the signal schema; its data is not used. The README says so above the fold.
9. **Authorship** appears only in the README: under the title and in the final *Author* section, the name Rodrigo Martín Gómez del Moral Herranz and, below it, the GitHub (`https://github.com/Rodrigo-GomezdelMoral`), LinkedIn (`https://www.linkedin.com/in/rodrigo-mart%C3%ADn-g%C3%B3mez-del-moral-herranz`) and portfolio (`https://rodrigogomezdelmoralherranz.es`) buttons. `LICENSE` is the standard Apache-2.0 text with no name; no author in package metadata; never an e-mail.
10. **README** follows the common final-README structure, with no *Quick start* and no local run instructions: the product is tried through the published demo.
11. **English** in everything the repository contains.

## Architecture in one paragraph

Per environment (`rg-trainyard-stg-swc`, `rg-trainyard-prod-swc`): one Container App behind Easy Auth serves FastAPI, the built web and one Agent Framework agent whose model client is `FoundryChatClient` on the shared `gpt-5-mini`. The agent only chooses tools and writes the explanation; every number comes from a tool. An Azure Machine Learning workspace runs the `prep → train → evaluate → register` pipeline on serverless `Standard_F2s_v2` with MLflow tracking; `evaluate` holds the gate and `register` obeys it. A managed online endpoint (`aad_token`, one `Standard_DS1_v2` instance, blue and green slots) serves `ml/score.py` with the data collector; a GA `MonitorSchedule` watches drift and data quality. The promotion is an Agent Framework workflow (shadow, canary, promote, rollback) with `request_info` approvals, checkpointed in Cosmos DB serverless, which also keeps the conversations. Shared, from the landing zone: the Basic registry, Foundry, Log Analytics and the action group. The champion is whatever serves 100 % of live traffic.

## SDK and API reference

Checked on 2026-10-30 against Microsoft Learn and PyPI. Each phase re-checks against the installed package before writing code.

| Purpose | Package and members |
|---|---|
| Agent | `agent-framework-core==1.23.0`: `Agent`, `tool` (`approval_mode="always_require"`), `Message`, `WorkflowBuilder`, executors with `ctx.request_info(...)` and `@response_handler`, `InMemoryCheckpointStorage` in tests. Run every conversation with a session: then only `always_require` tools wait for approval in a mixed batch (ADR-001) |
| Model client | `agent-framework-foundry==1.15.0`: `from agent_framework.foundry import FoundryChatClient`, `FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_MODEL`; needs `azure-ai-projects>=2.2.0,<2.8.0` |
| Checkpoints | `agent-framework-azure-cosmos==1.0.0b261015` (beta): `CosmosCheckpointStorage`; the Bicep creates the database and containers; if the class still fails against Entra-only Cosmos DB, a 30-line store in `app/` replaces it, with an ADR. Pass `container_client=`, which skips auto-creation; the checkpoint container has partition key `/workflow_name` and indexes `/timestamp`. The open promotion is the head of the checkpoint chain, never `get_latest` (timestamps tie; ADR-009). The same container holds the promotion lease, document `promotion` in partition `lease`, taken with create-if-absent or `If-Match` (ADR-009) |
| Conversations | Not `CosmosHistoryProvider`: an approval needs the session's `tool_approval` state, which the provider does not store. Each conversation is one document, `AgentSession.to_dict()`, in container `conversations` with partition key `/owner` (a SHA-256 prefix of the object id) and a 30-day default TTL (ADR-016) |
| Azure ML | `azure-ai-ml==1.35.2`: `MLClient`, `load_component`, `dsl.pipeline`, `ManagedIdentityConfiguration`, `ManagedOnlineDeployment`, `MonitorSchedule`; `endpoint.mirror_traffic`, `endpoint.traffic`. Call `pipeline(func, name=..., default_compute="serverless")` with the function, which mypy types; the decorator form without it does not type-check. Component specs in `ml/components/*.yaml` use `code: ../..`, with the `.amlignore` allowlist `/*` and `!/ml/` (gitwildmatch, last match wins; the SDK's upload walker lists only `ml/`), and an inline environment `build: path: ../environment`. A pipeline node's environment is on `node.component`. Unbound optional inputs are absent from `job._to_dict()`, but present on the node object. `azure-ai-ml` raises Marshmallow 4 deprecation warnings on import |
| Tracking | `mlflow==2.22.5` with `azureml-mlflow==1.62.0.post6`; not MLflow 3 (ADR-011). No stage tags or aliases: lineage and metrics are version tags, and the calibration and threshold are MLmodel `metadata`. `mlflow.lightgbm.save_model` creates the default store in the working directory, so the tests use a session store and the Makefile `.local/mlruns`. On Python 3.12, MLflow 2.22 warns about `datetime.utcnow()` and its own type hints; `pyproject.toml` ignores exactly those |
| Model | `lightgbm==4.7.0` (`LGBMClassifier`, `predict(..., pred_contrib=True)`), `scikit-learn==1.9.1` |
| Scoring | `azureml-inference-server-http==1.5.1` (`azmlinfsrv`), `azureml-ai-monitoring==1.0.0` (`Collector(name="model_inputs", on_error=...)`, `Collector(name="model_outputs", ...)`). Without `on_error`, the collector raises as soon as it is created when collection is off. `AZUREML_MDC_ENABLED=true` with `AZUREML_MDC_LOCAL_CAPTURE=true` logs each payload through the `local.capture` logger, which does not propagate. The base image's runit service runs `azmlinfsrv --entry_script $AZUREML_ENTRY_SCRIPT` from `AML_APP_ROOT`. `AZUREML_MODEL_DIR` is `azureml-models/<name>/<version>` (Learn). The inference server pins OpenTelemetry 1.33, so it lives only in `ml/environment`, never in the app's requirements |
| API | FastAPI 0.162.0 with its own Server-Sent Events (`fastapi.sse.EventSourceResponse`), `azure-identity`, `azure-cosmos==4.17.1`, `azure-monitor-opentelemetry==1.8.11`. KPI events are custom events: a log record on the `trainyard` logger with `microsoft.custom_event.name` (Learn and the installed exporter, ADR-016); `enable_trace_based_sampling_for_logs=False`. Easy Auth's `X-MS-CLIENT-PRINCIPAL` gives the roles; clients cannot set it. Tests use `fastapi.testclient` (`httpx`, dev only) and an in-memory OpenTelemetry log exporter |
| Data | `numpy==2.4.4`, `pandas==2.3.3`, `pandas-stubs==2.3.3.260113` for mypy. MLflow 2.22.5 requires `pandas<3`, and numpy 2.5 raises deprecation warnings under pandas 2.3.3 (checked in phase 1), so Dependabot ignores pandas majors and numpy minors. The Azure ML environment pins the same two versions: `ml/features.py` must give identical rows in the app and in `prep` |
| Load | `locust==2.47.0` |
| Bicep | `Microsoft.MachineLearningServices/workspaces` and `workspaces/onlineEndpoints@2026-09-01`; `Microsoft.App/containerApps` and `authConfigs@2026-07-01`; `Microsoft.Insights/workbooks@2023-06-01`, `scheduledQueryRules@2023-12-01`, `metricAlerts@2018-03-01`; `Microsoft.Consumption/budgets@2026-06-01`; storage `@2026-06-01`, Key Vault `@2026-02-01`, managed identities `@2024-11-30`; Cosmos DB: the latest GA, checked in phase 7 |

Python 3.12 everywhere, including the Azure ML environment.

## NOT VERIFIED, and the phase that settles it

| Question | Phase |
|---|---|
| `enableDataIsolation` with a Basic registry and a user-assigned identity | 7 (Learn), 8 (live) |
| Whether the workspace's grants to its own system identity run with the deployer's permissions (the role conditions allow both) | 8 |
| `agent-framework-azure-cosmos` against Entra-only Cosmos DB (phase 2: no auto-creation with `container_client`, and a full promotion round trip on the emulator) | 8 |
| Spark nodes per monitor run (cost), and whether `AmlRunStatusChangedEvent` carries the monitor's experiment name | 8 |
| The workspace building the environment from the build context `ml/environment` into the shared Basic registry, for serverless jobs and the online deployment (fallback: image plus conda file, measured in care-intel) | 8 |
| Easy Auth sign-in without a client secret | 8 |

## Environments and cost

| | Staging | Production |
|---|---|---|
| Deploys | every merge to `main`, by digest | the release, `v*` tags, after the owner's approval |
| Container Apps environment | its own, in swedencentral, never shared with another product | its own, in swedencentral, never shared with another product |
| Container App | max 2 replicas, scales to zero | max 3 replicas, scales to zero |
| Endpoint | 1 × `Standard_DS1_v2`, always on (ADR-004, ADR-005) | the same |
| Monitor | on demand | daily, 03:15 UTC |
| Budget (Bicep) | USD 60 | USD 80 |

- **Azure only in phases 8 and 9**, plus the shared model deployments from phase 2. Until then: local runs, emulators and `what-if`.
- **Pay-As-You-Go, no spending limit:** budgets only alert. Phase 8 states the price of anything billed by the hour and how to stop it before creating it; the endpoint deployments are deleted once recording and validation are done.
- **Azure ML quota in Sweden Central**, read on 2026-10-30, all unused: total dedicated cores 20; DSv2 6; FSv2 6; ESv3 20; Dv3 6; DSv3 6. One DS1_v2 instance reserves 2 cores, so DSv2 fits staging, production and one blue/green pair. **Never run blue/green in both environments at once.**
- **Staging ends every phase at zero** except the endpoint, whose cost the phase close states.
- Tags `project`, `environment`, `owner` on every resource; replica caps, tokens-per-minute quota, `max_tokens` and minimal log retention from the first resource.

## Phases

| # | Branch | Closes | Acceptance |
|---|---|---|---|
| 0 | `feature/setup` | setup check and quotas; `CLAUDE.md`, `.github/dependabot.yml`, `ci.yml`, `docs/PRODUCT.md` with BPMN maps, `tests/test_budget.py`, logo files | check table all green; CI green on the PR |
| 1 | `feature/domain` | `app/domain/simulator.py`, `ml/features.py`, fleet ranking under the inspection budget, explanation templates, `data/README.md`; no AI | seeded simulation reproducible; feature parity test; failures preceded by degradation |
| 2 | `feature/agents` | agent, tools with an endpoint double, promotion workflow with `request_info` and checkpoints, role filtering; real `gpt-5-mini`, doubles in tests | a `Reader` cannot reach approval tools; the workflow resumes from a checkpoint; numbers in answers equal tool output |
| 3 | `feature/training` | components, pipeline, local MLflow, the gate, `score.py` with the collector under `azmlinfsrv`, the environment in local Docker; ADR-003, -006, -008, -011 | `make train-local` runs the four steps (dry run) and logs to MLflow; the gate refuses a worse challenger; `score.py` answers 40 rows in Docker |
| 4 | `feature/eval` | `eval/` datasets, evaluators, runner and thresholds, `eval.yml`, `docs/evaluation.md`, `RESPONSIBLE_AI.md` | agent eval against the real model meets thresholds; `eval.yml` fails a PR that breaks one |
| 5 | `feature/api` | FastAPI, Easy Auth headers and roles, KPI events, feedback, deletion, timeouts, retries, `429`, `/healthz` | every KPI event reaches a local OpenTelemetry exporter; 401/403 tests; dependency-down tests answer clearly |
| 6 | `feature/web` | the common interface and its demo mode | axe clean; demo mode builds without a backend |
| 7 | `feature/infra` | Bicep with `what-if` on both groups, `deploy.yml`, `release.yml`, `load-test.yml`, `pages.yml`, `THREAT_MODEL.md`, `OPERATIONS.md`, `cost.md` | `bicep build` and lint clean; `what-if` shows only creations, every role assignment within the conditions |
| 8 | `feature/staging` | first deployment to staging and everything live: login script, seed, pipeline, first model, `firmware-b` drift, monitor, retrain, shadow, canary, rollback, promotion, Locust, restore drill, KPIs and SLOs, Advisor | every `Must` shown in staging as the customer would use it, with the final state on screen; load results meet the SLAs |
| 9 | `feature/release` | `CHANGELOG.md`, recorded runs, `pages.yml` published, README, `v1.0.0` ready | demo published; after the merge, the `gh release create v1.0.0` command |

CodeQL default setup is switched on once `main` has code: phase 1 checks it after the first pull request with code and gives the owner the command if it is missing.

## Guidance map

| Decision | Source (`_00_MASTER_PROMPTS_CLOUD/_syllabus/`) |
|---|---|
| Agent, tools, approval | Agent Framework guide 0.4, 5.1 (lines 1337–1450), 7.1.2 |
| Promotion workflow, checkpoints | guide 6.2 (2032–2070), 6.3 (2078–2091), 7.4 (2773–2780) |
| Self-hosting in Container Apps | guide 8.1 (2963–3012); AI-200 LP2 M1–M3 (2553, 3149, 3757) |
| MLflow, jobs, components, pipeline | AI-300 LP1 M2 (459), M3 (838, 880, 954), M5 (1860, 1970, 2061) |
| Deployment, environments, OIDC | AI-300 LP1 M10 (3293), M7–M9 (2740, 3038, 3181), extras (3339, 3369, 3397) |
| Monitoring, retraining | AI-300 LP1 M6 (2612, 2643), extra (3426) |
| Agent evaluation | AI-300 LP2 M4 (5742, 6033) |
| Tracing and telemetry | AI-300 LP2 M5–M6 (7013, 7060, 7591); AI-200 LP9 (21338) |
| Cosmos DB | AI-200 LP4 M1 (7406), M3 (9671) |
| Secrets | AI-200 LP8 M1 (19835) |
| Responsible AI, guardrails | AI-103 (128), Module 6 (2985, 3131) |

Well-Architected, applied without raising cost: Reliability RE:01, RE:02, RE:03, RE:04, RE:07, RE:09, RE:10; Security SE:02, SE:04, SE:05, SE:06, SE:08, SE:09, SE:12; Cost CO:02, CO:03, CO:04, CO:07, CO:08, CO:09, CO:10, CO:12; Operational excellence OE:03, OE:04, OE:05, OE:06, OE:07, OE:08, OE:11; Performance PE:01, PE:06, PE:07. Trade-offs that raise cost or depart from guidance live in ADRs 001 to 016.
