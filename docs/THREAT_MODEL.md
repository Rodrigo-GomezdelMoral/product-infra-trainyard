# Threat model

A light STRIDE pass over Trainyard as deployed by `infra/main.bicep`. Each mitigation names the test or the check that shows it. State on 2026-10-31: implemented, tested locally and validated with `what-if`; nothing is deployed yet (phase 8).

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
| **Tampering** with the image | the registry | One image per commit, deployed by digest; production deploys the digest recorded on the tag's commit | `deploy.yml` (`staging-image` status), `release.yml` (verify job) |
| **Repudiation** of an approval | the promotion | Every approval is an `approval_given` event with a hash of the approver's object id, the model version and the step | `test_promotion_cards_through_the_chat`; the workbook's events |
| **Information disclosure** | prompts, logs, repository | Synthetic equipment data only; conversations keep a hash of the object id; local auth off on Cosmos DB, storage (shared key) and Application Insights; no keys or connection secrets anywhere | `test_no_identifiers`; `disableLocalAuth`, `allowSharedKeyAccess: false` in `what-if` |
| **Denial of service** | app, endpoint, model | Replica caps (2 in staging, 3 in production), one endpoint instance with platform limits, `max_tokens`, the deployment's tokens-per-minute quota, a clear `429` with `Retry-After` | `test_dependency_down`; Locust's stress scenario (phase 8) |
| **Elevation of privilege** | the agent | Tools are filtered by app role on the server before the model sees them; a `Reader` cannot reach `start_retraining`, `start_promotion` or `rollback`; prompt injection never reaches an approval tool, because every such tool waits for a human | `test_reader_cannot_promote`, `test_retraining_waits_for_approval`, the agent evaluation in `eval.yml` |
| **Elevation of privilege** | CI | Each CI principal holds Contributor on its own group only. It can grant only the roles its conditions list, at the scopes they cover, and it holds no right to change a shared resource. | `what-if`: 13 Azure role assignments per environment, all within the conditions (phase 7) |

## Residual risks, accepted

- **First deployment window.** Azure creates the Container App before its `authConfigs` child, so for seconds on the very first deployment the app is reachable without Easy Auth. With no session it has no data, the image is not yet serving users, and the window never recurs.
- **No private networking.** Public endpoints with Entra ID and TLS 1.2, no private endpoints or managed virtual network. They would add cost, and model monitoring does not support approved-outbound-only isolation (Guidance map, Security).
- **Shared base.** The registry, Foundry, Log Analytics and the action group are shared with other products; Trainyard only adds role assignments there (ADR-007).
- **One instance.** Availability rests on the platform replacing an unhealthy instance (ADR-005).
