# Threat model

A light STRIDE pass over Trainyard as deployed by `infra/main.bicep`. Each mitigation names the test or the check that shows it. State on 2026-11-04: deployed to staging (2026-11-01) and to production (`v1.0.0`, 2026-11-03). Checked live in production on 2026-11-04: every route but `/healthz` answers 401 without a session, a forged `X-MS-CLIENT-PRINCIPAL` header is refused, the endpoint refuses a call without a token, and no Trainyard principal holds Owner or a subscription-scope role.

## Assets and trust boundaries

- **Assets:** the champion model and its lineage, the traffic split of the endpoint, the promotion's approvals, the fleet feed, the conversations, the budget.
- **Boundaries:**
  - the internet → Easy Auth on the Container App;
  - the app → the endpoint, Azure Machine Learning, Cosmos DB and Foundry, each with the app's managed identity;
  - GitHub Actions → Azure, with OIDC and one principal per environment.

## STRIDE

| Threat | Where | Mitigation | Shown by |
|---|---|---|---|
| **Spoofing** a user | the app | Easy Auth with Entra ID (`RedirectToLoginPage`, token store off) is the only ingress; only `/healthz` is excluded. The app reads roles from `X-MS-CLIENT-PRINCIPAL`, which Container Apps sets and clients cannot. | `test_sign_in_and_roles` (401 without the header, 403 without a role); `authConfigs` in the `what-if` of both groups |
| **Spoofing** a caller of the endpoint | the endpoint | `aad_token`: no keys exist; only identities with the score action are let in | `authMode: AADToken` in `what-if` |
| **Tampering** with the model | the workspace | A model enters only through the gated `register`; deployments change only through the promotion workflow, after a `ModelApprover`'s approval | `test_gate_refuses_worse`, `test_register_tags_lineage`, `test_reader_cannot_promote` |
| **Tampering** with the traffic by a deployment | the endpoint | Every Bicep deployment passes the live and mirrored traffic back unchanged (ADR-004) | `traffic` and `mirrorTraffic` read by `.github/actions/ship` before each deployment |
| **Tampering** with the image | the registry | One image per commit, deployed by digest; production deploys the digest recorded on the tag's commit; `v*` tags cannot be moved or deleted (ruleset `protect-release-tags`) | `deploy.yml` (`staging-image` status), `release.yml` (verify job), the repository's rulesets |
| **Repudiation** of an approval | the promotion | Every approval is an `approval_given` event with a hash of the approver's object id, the model version and the step | `test_promotion_cards_through_the_chat`; the workbook's events |
| **Information disclosure** | prompts, logs, repository | Synthetic equipment data only; conversations keep a hash of the object id; local auth off on Cosmos DB, storage (shared key) and Application Insights; no keys or connection secrets anywhere | `test_no_identifiers`; `disableLocalAuth`, `allowSharedKeyAccess: false` in `what-if` |
| **Denial of service** | app, endpoint, model | Replica caps (2 in staging, 3 in production), one endpoint instance with platform limits, `max_tokens`, the deployment's tokens-per-minute quota, a clear `429` with `Retry-After` | `test_dependency_down`; Locust's stress scenario (phase 8) |
| **Elevation of privilege** | the agent | Tools are filtered by app role on the server before the model sees them; a `Reader` cannot reach `start_retraining`, `start_promotion` or `rollback`; prompt injection never reaches an approval tool, because every such tool waits for a human | `test_reader_cannot_promote`, `test_retraining_waits_for_approval`, the agent evaluation in `eval.yml` |
| **Elevation of privilege** | CI | Each CI principal holds Contributor on its own group only. It can grant only the roles its conditions list, at the scopes they cover, and it holds no right to change a shared resource. On `cae-trainyard-env`, which production owns, the staging principal holds only `read` and `join/action` (ADR-018). | `what-if`: 13 Azure role assignments per environment, all within the conditions (phase 7) |

## Residual risks, accepted

- **Dependencies with open advisories (2026-11-04).** The 29 Dependabot alerts on `mlflow==2.22.5` and `pyarrow==19.0.1` are dismissed one by one with their reason: 24 affect code Trainyard never runs (the MLflow server, UI, gateway and model server; Arrow IPC files) and 5 touch only its own gated artifacts on single-tenant, ephemeral runners and job nodes. MLflow is not in the app image. The assessment per advisory is in ADR-011.
- **Production lineage names the release tag.** In production the `git_sha` tag carries the tag (`v1.0.0`), not the commit; the tag ruleset keeps it on one commit (ADR-011).
- **Public workflow logs before `v1.0.1`** print the sign-in app's client id, a public identifier of the app registration, not a credential. From `v1.0.1` it is an environment secret, which GitHub masks in every line; old logs stay as the delivery record.

- **First deployment window.** Azure creates the Container App before its `authConfigs` child, so for seconds on the very first deployment the app is reachable without Easy Auth. With no session it has no data, the image is not yet serving users, and the window never recurs.
- **Two regions.** The app runs in Germany West Central and its data stays in Sweden Central (ADR-017): conversations and scores cross between them over TLS 1.2 on the Microsoft backbone, with the same Entra ID checks at every hop, and nothing is kept at rest in Germany West Central.
- **One Container Apps environment for staging and production** (ADR-018). They share its log destination, default domain, internal network and platform upgrades; apps, identities, data, sign-in and scaling stay separate, and only a reviewed release changes the environment.
- **No private networking.** Public endpoints with Entra ID and TLS 1.2, no private endpoints or managed virtual network. They would add cost, and model monitoring does not support approved-outbound-only isolation (Guidance map, Security).
- **Shared base.** The registry, Foundry, Log Analytics and the action group are shared with other products; Trainyard only adds role assignments there (ADR-007).
- **One instance.** Availability rests on the platform replacing an unhealthy instance (ADR-005).
