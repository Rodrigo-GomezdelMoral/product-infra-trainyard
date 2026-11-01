# ADR-007 · The shared registry, with workspace data isolation

**Status:** accepted · **Date:** 2026-10-31

## Context

The landing zone already runs a Basic container registry, `craiplatformshared`, with the admin user disabled. Trainyard needs it for the app image, and for the environment image that each workspace builds for training and scoring. Two workspaces writing environment images into one registry could overwrite each other's repositories.

## Options

1. **A registry per environment.** About USD 5 a month each. The image would have to be rebuilt or copied for production, which breaks "build once, promote by digest" (OE:06).
2. **The shared registry, without data isolation.** Both workspaces would write the same repositories.
3. **The shared registry, with `enableDataIsolation: true`** on each workspace, so that each workspace's images are kept apart.

## Decision

**Option 3.**
- **The app image** is built once per commit by the staging principal, tagged `YYYYMMDD-main-<sha>`, and promoted to production by digest. `deploy.yml` records the digest on the commit as the status `staging-image`, and `release.yml` deploys exactly that digest.
- **Access:** the app, the jobs and the endpoint pull with `AcrPull`. The workspace's primary identity, `id-trainyard-aml-<env>`, also holds `Azure AI Administrator` on the registry, where Learn requires Contributor so that the workspace can build and push its environment images (ADR-006). The CI principals may assign both roles there, under the conditions of `01-azure.sh`.
- **Linking the registry:** ARM checks `Microsoft.ContainerRegistry/registries/write` on the linked registry at every PUT of a workspace that links it. The first attempt of the first staging deployment failed with `LinkedAuthorizationFailed`. The owner's `05-registry-link.sh` gives each CI principal the custom role *Trainyard registry link*, with `registries/read` and `registries/write` only, assignable on the shared registry only. It grants no data-plane right: pushing and pulling stay with the roles above.
- **The shared resource group receives only role assignments,** through one nested deployment per environment (`infra/modules/shared.bicep`). Role Based Access Control Administrator cannot create a deployment there. Each CI principal therefore also needs `Microsoft.Resources/deployments/*` on that group, plus two monitoring grants: Monitoring Contributor on the shared Log Analytics workspace (Application Insights and the diagnostic settings link to it), and Monitoring Reader on the shared action group (every alert rule reads it). The owner gives them with `02-shared-access.sh`.

## State

- **Learn, checked 2026-10-31:** `enableDataIsolation` is "a flag to determine if a workspace has data isolation enabled", which "can only be set at the creation stage" (Learn, `az ml workspace create --enable-data-isolation`). Learn documents no restriction with a Basic registry or with a user-assigned primary identity, and does not describe the repository layout it produces.
- **Validated with `what-if`** in both groups. The template uses API version 2026-09-01, which the Bicep CLI 0.48.1 has no types for; its properties were type-checked against 2026-07-01, the newest version the CLI knows.
- **Phase 8:** `05-registry-link.sh` run by the owner and its two assignments verified; the next deployment carries the workspace identity's grant on the registry.
- **Measured in phase 8 (2026-11-01):** the staging workspace was created from a template that sends `enableDataIsolation: true`, the deployment succeeded, and the live workspace reads `false` (GET with API versions 2026-09-01 and 2025-06-01). The service drops the flag without an error, and it cannot be set after creation. Option 3 is therefore not in effect, and the context's risk (two workspaces writing the same repositories) stands until the first pipeline run shows how the environment images are named.
- **Measured on the first pipeline run (2026-11-01):** the staging workspace built the environment from `ml/environment` once (an image-build run, then all four serverless steps ran on it) and pushed it to one repository, `azureml/azureml_<hash>`, with no workspace prefix. The name is a hash of the environment definition, not of the workspace: production, building the same definition, would write the same repository with the same content, and a changed definition gets a new repository. The overwrite risk of the context reduces to two identical builds of one definition. The online deployment on that image is read on the first model deployment.

## Consequences

- Data isolation cannot be switched on later: changing it means a new workspace.
- The registry and its cost belong to the shared base, not to Trainyard.
- Each CI principal can change the shared registry's configuration (`registries/write`). Each workspace identity holds `registries/*` there: it can also delete the registry, read or regenerate its credentials, and, since the registry does not use repository-scoped permissions, push and pull any repository, other products' included. That identity also runs every pipeline node, so job code holds the same rights. Learn requires Contributor here, which is wider; the trade-off is accepted because the registry holds only images promoted by digest, the admin user stays disabled, and the jobs run only components registered from `main` with the image's version.
