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
- **Access:** the workspaces reach the registry with their identities; the app, the jobs and the endpoint have `AcrPull` only.
- **The shared resource group receives only role assignments,** through one nested deployment per environment (`infra/modules/shared.bicep`). Role Based Access Control Administrator cannot create a deployment there. Each CI principal therefore also needs `Microsoft.Resources/deployments/*` on that group, plus two monitoring grants: Monitoring Contributor on the shared Log Analytics workspace (Application Insights and the diagnostic settings link to it), and Monitoring Reader on the shared action group (every alert rule reads it). The owner gives them with `02-shared-access.sh`.

## State

- **Learn, checked 2026-10-31:** `enableDataIsolation` is "a flag to determine if a workspace has data isolation enabled", which "can only be set at the creation stage" (Learn, `az ml workspace create --enable-data-isolation`). Learn documents no restriction with a Basic registry or with a user-assigned primary identity, and does not describe the repository layout it produces.
- **Validated with `what-if`** in both groups. The template uses API version 2026-09-01, which the Bicep CLI 0.48.1 has no types for; its properties were type-checked against 2026-07-01, the newest version the CLI knows.
- **NOT VERIFIED until phase 8:** the repositories each workspace writes in the shared registry, and the environment built from `ml/environment` into it.

## Consequences

- Data isolation cannot be switched on later: changing it means a new workspace.
- The registry and its cost belong to the shared base, not to Trainyard.
