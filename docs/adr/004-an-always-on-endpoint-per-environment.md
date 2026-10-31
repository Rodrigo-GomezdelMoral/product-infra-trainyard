# ADR-004 · A separate, always-on endpoint per environment

**Status:** accepted · **Date:** 2026-10-31

## Context

The inference endpoint is the SLA surface (REQ-07, REQ-08, ADR-014). Its data collector writes each environment's production inputs and outputs, which the drift monitor reads (REQ-04). A managed online endpoint cannot scale to zero: a deployment bills every hour it exists (Learn, concept-endpoints, 2026-08-21).

## Options

1. **One endpoint shared by both environments.** Half the cost. But staging traffic and load tests would mix with production's, its collector would write both environments' data into one storage, and one identity would serve both (SE:04).
2. **A batch endpoint or serverless scoring.** No idle cost, but no interactive latency, so REQ-08 could not be met.
3. **One managed online endpoint per environment,** in its own workspace, with its own identity and storage.

## Decision

**Option 3.** The Bicep creates the endpoint: `aad_token`, `id-trainyard-ep-<env>`, and diagnostic settings for the traffic, console and event logs. The deployments are the model lifecycle: the promotion workflow creates them, never the Bicep. Every deployment of the Bicep passes the live and mirrored traffic back unchanged, read just before it runs, so a merge never moves traffic.

The rest of each environment is separated too: resource group, budget, identities, workspace, storage, Key Vault, Application Insights, Cosmos DB and the Container Apps environment. The Key Vault has purge protection in production only, because purge protection reserves the name for the whole retention period.

## State

- **Implemented and validated with `what-if`** in both groups (phase 7): 39 creations each, and nothing else.
- **Pending:** the first deployment and its measured cost (phase 8).

## Consequences

- About USD 49.57 a month per environment for one `Standard_DS1_v2` instance, while a deployment exists (`docs/cost.md`). Deleting the deployments stops it; the endpoint, the models and the data stay.
- A redeploy reads the traffic seconds before it applies it. A promotion step that changes traffic in that window would be undone, so `OPERATIONS.md` says not to merge while a promotion step is running.
