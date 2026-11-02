# ADR-018 · One Container Apps environment for staging and production

**Status:** accepted · **Date:** 2026-11-02

## Context

ADR-017 put one environment per Trainyard environment in `germanywestcentral`: `cae-trainyard-stg-gwc`, deployed, and `cae-trainyard-prod-gwc`, which release `v1.0.0` would create. On 2026-11-02 the subscription has two limits, and production cannot get an environment under either:

- **5 environments per subscription.** ARM preflight of `infra/modules/environment.bicep` with concrete values, in `rg-trainyard-prod-swc`, answers `MaxNumberOfGlobalEnvironmentsInSubExceeded`, "cannot have more than 5 Container App Environments", in `germanywestcentral` and in `italynorth` alike. Five exist across the portfolio's products, one of them `cae-trainyard-stg-gwc`. The usages API and the quotas page do not show this limit.
- **1 environment per region.** The usages API (`Microsoft.App/locations/<region>/usages`, `ManagedEnvironmentCount`) reads 1 of 1 in `germanywestcentral`. ADR-017 read 0 of 5 there on 2026-11-01.

`az deployment group validate` and `what-if` of `infra/main.bicep` see neither limit: the modules take runtime values, and preflight skips a module whose parameters it cannot resolve. Another product's release `v1.0.0` failed this way after its preflight passed. Only a module or a bare resource validated with concrete values reaches the `Microsoft.App` provider. A preflight of `infra/modules/app.bicep` with concrete values succeeds both with the current environment and with `cae-trainyard-env` before it exists, so preflight does not check the environment an app joins either.

## Options

1. **Quota increases** for both limits: a support request with no date, and the release waits.
2. **Production joins the staging environment.** No quota, but production would run in an environment named, owned and torn down as staging.
3. **Express environments.** They have no built-in authentication (Easy Auth, REQ-06), no custom KEDA scalers and no revision labels.
4. **One environment per product,** `cae-trainyard-env`, with a neutral name, declared by production and joined by both apps.

## Decision

Option 4, the owner's decision, the same for every product in the subscription.

- `infra/modules/environment.bicep` declares `cae-trainyard-env`: `Consumption` workload profile, logs to Azure Monitor, no zone redundancy, and a diagnostic setting to the shared Log Analytics workspace, as the per-environment ones had.
- Only the production deployment declares it, in the existing `rg-trainyard-prod-swc`, in `germanywestcentral` (`appLocation`), tagged `environment: shared`. No resource group is created.
- The staging deployment refers to it as `existing` in that group and never writes it. `ca-trainyard-stg` stays in `rg-trainyard-stg-swc` and `ca-trainyard-prod` in `rg-trainyard-prod-swc`; both run in `germanywestcentral`.
- Staging deploys on every merge, before any release, so the owner's `10-environment.sh` bootstraps the environment once:
  1. it deletes `ca-trainyard-stg` and `cae-trainyard-stg-gwc` first, because the subscription allows no sixth environment and the region no second one;
  2. it deploys `environment.bicep` with the values `main.bicep` passes, so the first release finds no drift;
  3. it grants the staging CI principal a custom role, `Trainyard environment join`, on the environment alone: `Microsoft.App/managedEnvironments/read` and `Microsoft.App/managedEnvironments/join/action` ("Allows to create a Container App in a Managed Environment", Learn, *Azure permissions for Compute*).
- The environment's settings change only through a reviewed release, because production's lifecycle governs them: removing staging never touches the environment, and the staging principal can join it but not change it.

## Consequences

- **What is ceded.** Staging and production share the environment's configuration: its log destination, its networking (one default domain and one internal network, without a virtual network in either case) and the platform's upgrades and availability. A change to the environment is not rehearsed in staging first; the release's `what-if` shows it.
- **What stays separate.** The apps, their user-assigned identities, Cosmos DB accounts, workspaces, endpoints, sign-in app registrations, Easy Auth configuration, scale rules, maximum replicas and revisions, as in ADR-017, and the blast radius between products (SE:04).
- **Staging is down during the change,** from the deletion of `ca-trainyard-stg` until `deploy.yml` recreates it after the merge. Cosmos DB, the workspace and the endpoint are untouched, so conversations, checkpoints, models and traffic survive.
- **Host names change.** The new environment has a new default domain, so `03-login.sh <env>` runs again after the first deployment of each app into it, to register the new sign-in callback.
- **Removal.** Deleting `rg-trainyard-prod-swc`'s resources deletes the environment and stops staging too. Removing staging deletes only `ca-trainyard-stg`.
- **Count.** Trainyard uses 1 of the subscription's 5 environments; one per product, the portfolio's four products use 4.
- **Price.** Unchanged: a Consumption environment costs nothing at rest, and the apps keep their region, so latency and inter-region transfer are as in ADR-017.
- **Preflight.** Before changing the environment's region or properties, validate `environment.bicep` on its own with concrete values; `main.bicep`'s `validate` and `what-if` will not show either limit.
