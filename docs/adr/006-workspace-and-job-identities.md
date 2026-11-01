# ADR-006 · Workspace and job identities

**Status:** accepted · **Date:** 2026-10-31

## Context

The training pipeline runs on serverless compute and pulls its environment image from the shared Basic registry, whose admin user is disabled. Its steps read the fleet feed and write models to the workspace storage, which has shared keys disabled (`systemDatastoresAuthMode: identity`). The endpoint pulls the same image and writes the collected production data. The Container App submits pipelines, changes traffic and reads models. Every one of these calls needs an Entra ID identity with exactly the roles it uses, and staging and production must never share one (SE:04, SE:05).

`azure-care-intelligence-platform` measured the constraints on 2026-10-20:

- Serverless compute accepts no system-assigned identity.
- With the submitter's user identity, a serverless node cannot pull the step image from an admin-disabled registry ("Failed to pull Docker image", even with `AcrPull` on the workspace identity).
- A job that runs as a user-assigned identity needs its submitter to hold `Managed Identity Operator` on that identity.

## Options

1. **The workspace's system-assigned identity for everything.** Serverless rejects it for jobs, and it would mix the workspace's own grants with the jobs' data access.
2. **The submitter's identity** (the CI principal, or the app's). Nodes cannot pull the image, and every submitter would need data roles on the storage.
3. **One user-assigned identity per purpose and per environment,** created by the Bicep:
   - `id-trainyard-aml-<env>`, the workspace's user-assigned identity, set on every pipeline node;
   - `id-trainyard-ep-<env>` for the endpoint;
   - `id-trainyard-app-<env>` for the Container App.

## Decision

**Option 3.** The workspace has `SystemAssigned,UserAssigned`. The system identity keeps the grants that the workspace makes to itself at creation, and the Bicep never declares them, because declaring them fails with `RoleAssignmentExists` (measured in care-intel).

| Identity | Roles | Used for |
|---|---|---|
| `id-trainyard-aml-<env>` | `Azure AI Administrator` (workspace, its storage, Key Vault and Application Insights, and the shared registry), `Key Vault Administrator` (Key Vault), `Storage Blob Data Contributor` (workspace storage), `AcrPull` (shared registry) | the workspace's primary identity, which reaches the associated resources from its creation on; every pipeline node: pulls the environment image, reads the feed, writes outputs and the MLflow model |
| `id-trainyard-ep-<env>` | `AcrPull` (shared registry), `Storage Blob Data Contributor` (workspace storage) | the endpoint: pulls the image, reads the model, writes collected data |
| `id-trainyard-app-<env>` | `AzureML Data Scientist` (workspace), `Managed Identity Operator` (on `id-trainyard-aml-<env>`, and on `id-trainyard-ep-<env>`, because changing the traffic is a PUT of the endpoint, which carries its identity), `Monitoring Reader` (the endpoint only: the traffic log, phase 8), `Storage Blob Data Reader` (workspace storage), `AcrPull` (shared registry), `Cognitive Services OpenAI User` (Foundry account), `Foundry User` (Foundry project), `Monitoring Metrics Publisher` (Application Insights), Cosmos DB Built-in Data Contributor (a SQL role assignment) | runs the app: submits the pipeline as `id-trainyard-aml`, changes traffic, reads models, scores with `aad_token`, and reaches the model, telemetry and conversations |

- **In `ml/pipeline.py`,** `build()` sets `ManagedIdentityConfiguration(client_id=...)` on the pipeline job and on each of its four nodes. This is the measured care-intel pattern. The client id arrives as a parameter, from a Bicep output in the workflows and from an environment variable in the app, and is never written in the repository.
- **The job gets its name before submission** and passes it to `register` as `pipeline_job`. The model's lineage then names the job that produced it, with no dependence on an undocumented environment variable inside the job (REQ-01). `AZUREML_ROOT_RUN_ID` is not in Learn's documentation.

## State

- **Implemented and tested** in the pipeline definition (`test_pipeline_builds` checks the identity and the instance type on every node, and the job name in the lineage).
- **Implemented and validated with `what-if`** (phase 7): the three identities and their roles in `infra/main.bicep`; the workspace's primary user-assigned identity is `id-trainyard-aml-<env>`, which Learn also makes the default identity of serverless compute. In both groups, the 13 Azure role assignments fall within the CI principals' conditions, and the Cosmos DB data role is a SQL role assignment.
- **Phase 8:** `Monitoring Reader` is outside the conditions `01-azure.sh` set, so `04-staging-access.sh` (owner) adds it to the roles each CI principal may assign in its own group. `Managed Identity Operator` already was.
- **Phase 8, second attempt of the first staging deployment** (the first stopped at the registry link, ADR-007): the workspace failed with `BadRequest`, because its primary identity had no `Microsoft.KeyVault/vaults/read` on the vault. Learn (*Set up authentication between Azure Machine Learning and other services*, updated 2026-01-22) requires the primary user-assigned identity to hold Contributor on the workspace, its storage, its Key Vault, its registry and its Application Insights, plus Key Vault Administrator on an RBAC vault and Storage Blob Data Contributor on the storage. Contributor is outside the CI conditions, and on a job identity it would reach every resource type. `Azure AI Administrator` is in both conditions and holds the same actions on these five resource types (`Microsoft.MachineLearningServices/workspaces/*`, `Microsoft.Storage/storageAccounts/*`, `Microsoft.KeyVault/*`, `Microsoft.ContainerRegistry/registries/*`, `Microsoft.Insights/components/*`; Learn, built-in roles). It is assigned on each resource, never on the group, where it would also reach Cosmos DB, and it replaces `AzureML Data Scientist` on the workspace, of which it is a superset (that role has no data actions). The vault, storage, Application Insights and registry grants precede the workspace (`dependsOn`); the workspace grant follows it, because its scope does not exist before. The template now holds 20 Azure role assignments, all within the roles `01-azure.sh` and `04-staging-access.sh` let each CI principal assign: no condition changes. The registry link alone needed `05-registry-link.sh` (ADR-007).
- **Propagation:** Learn (*Troubleshoot Azure RBAC*) gives a new role assignment up to 10 minutes to take effect, and these grants are created seconds before the workspace. The ship action therefore retries a failed deployment once, after 10 minutes.
- **Pending:** the first live run (phase 8).
- **Settled in phase 8 (2026-11-01):** the workspace makes no grant to its own system identity, which holds no role assignment in staging. With a primary user-assigned identity, every grant on the storage, the vault, the workspace and the registry is one of the template's, created by the CI principal within its conditions. The staging workspace was created with `Azure AI Administrator` in place of Contributor; the environment build into the registry is read on the first pipeline run.

## Consequences

- **Three identities per environment, six in all,** each with the narrowest roles its calls need.
- **Retraining from the chat** runs as `id-trainyard-aml`, through the app's `Managed Identity Operator` on it. The app never holds data-plane roles on the workspace storage beyond `Storage Blob Data Reader`.
- **The data collector writes as the endpoint identity,** so collected production data can only reach that environment's storage.
