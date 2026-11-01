# ADR-017 · The Container Apps environment and app in Germany West Central

**Status:** accepted · **Date:** 2026-11-01

## Context

The first deployment to staging never reached the app module, and its preflight would have failed there. On 2026-11-01 the Container Apps usages in Azure Resource Manager (`Microsoft.App/locations/<region>/usages`, `ManagedEnvironmentCount`) and a preflight of `infra/modules/app.bicep` (`az deployment group validate`, read-only) gave:

| Region | Environments used / limit | Preflight of the environment and the app | P50 round trip to Sweden Central |
|---|---|---|---|
| `swedencentral` | 1 / 1, another product's staging | `MaxNumberOfRegionalEnvironmentsInSubExceeded` | |
| `westeurope` | 0 / 5 | `RequestDisallowedByAzure`: "The selected region is currently not accepting new customers" | 27 ms |
| `germanywestcentral` | 0 / 5 | succeeds | 27 ms |
| `polandcentral` | 0 / 5 | succeeds | 26 ms |
| `norwayeast` | 0 / 5 | succeeds | 12 ms |
| `northeurope`, `francecentral`, `italynorth`, `spaincentral` | 0–1 / 5 | succeeds | 33–50 ms |

The quota limit counts environments per subscription and region. The usages API does not show the region restriction: only preflight shows it. Round trips are from Learn's *Azure network round-trip latency statistics* (2026-07-30). The build prompt placed both environments in `swedencentral`, each never shared with another product.

## Alternatives

1. **Ask for more quota in `swedencentral`.** It needs a support request with no known turnaround, and it blocks the phase until then. It stays open: see *Moving back*.
2. **Use the other product's environment.** That breaks the rule that no environment is shared between products (SE:04): one blast radius, one set of logs and one bill per product.
3. **Move the whole product.** The workspace, storage, Key Vault and identities already exist in `swedencentral`, and the Azure ML quota was read there (ADR-005). Moving them would change data residency and the measured quota, all for an environment that costs nothing at rest.
4. **`westeurope`, the owner's first choice.** Azure refuses new resources from this subscription there.
5. **`norwayeast`.** It is the fastest, at 12 ms, but it is outside the European Union.
6. **`germanywestcentral`.** It is in the EU, has the same 27 ms as `westeurope`, the same Container Apps prices as `swedencentral` and the full service set. `polandcentral` would be equivalent at 26 ms, but it is a newer region.

## Decision

Option 6, which replaces the owner's `westeurope`. Only the Container Apps environment and the app move. `infra/main.bicep` takes `appLocation`, default `germanywestcentral`, for both environments, and `infra/modules/app.bicep` uses it for the environment and the app only. The environments are `cae-trainyard-stg-gwc` and `cae-trainyard-prod-gwc`, and the region code follows `appLocation`. The app keeps its name, `ca-trainyard-<env>`, so the owner's sign-in script and the workflows do not change: they read the app by name and its host from the app. Resource groups, identities, Cosmos DB, the workspace, storage, Key Vault, Application Insights, the endpoint, the alerts and the workbook stay in `swedencentral`.

## Consequences

- **Latency.** Each call from the app to Cosmos DB, the endpoint's scoring URI, the workspace or Application Insights crosses a 27 ms round trip. A chat turn (read and write the session, one or two tool calls) gains about 0.1–0.2 s against the 3 s time-to-first-token SLO. The SLA (REQ-07, REQ-08) is measured at the endpoint, server side, so it does not change. Locust's `/api/fleet/risk` scenario measures the app path end to end.
- **Residency.** Data at rest stays in Sweden Central. The app handles requests in memory in Germany West Central. The environment's logs go to the shared Log Analytics workspace in Sweden Central through its diagnostic setting, which accepts a workspace in any region. Traffic between the two regions uses TLS 1.2 on the Microsoft backbone. The user-assigned identity `id-trainyard-app-<env>` stays in Sweden Central and is attached to the app across regions. Another product in this subscription runs the same pattern from `spaincentral`.
- **Price.** Container Apps prices in Germany West Central equal Sweden Central's: USD 0.000024 per vCPU-second, 0.000003 per GiB-second and 0.40 per million requests (Retail Prices API, 2026-11-01). Inter-region transfer adds USD 0.02 per GB, for image pulls from the shared registry and the responses. `docs/cost.md` keeps its totals.
- **Moving back.** A Container App cannot change region. To return to `swedencentral` once quota allows, delete `ca-trainyard-<env>` and its environment, then deploy with `appLocation` set to `swedencentral`. That needs a new sign-in callback (`03-login.sh`). Before choosing any other region, run the same preflight: the usages API alone does not show a refused region.
