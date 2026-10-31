# ADR-016 · The API: sign-in from Easy Auth, one document per conversation, KPI events as custom events

**Status:** accepted · **Date:** 2026-10-31

## Context

Phase 5 puts the agent, the promotion cards and the product's own blocks behind one FastAPI app (`app/main.py`): sign-in and roles, KPI events, feedback (REQ-09), deletion (REQ-10), timeouts, retries and a clear answer when a dependency is down or throttled. Three choices were not settled by the build prompt or departed from it.

## Decisions

### Sign-in and roles come from Easy Auth

Container Apps authentication signs the user in and injects `X-MS-CLIENT-PRINCIPAL` (phase 8 configures it). The app only reads it:
- **No header or an unreadable one:** 401.
- **No `Reader` or `ModelApprover` role, or no object id:** 403.
- **Promotion cards** (`/api/promotion`): `ModelApprover` only. The agent's tools are filtered by the same roles (ADR-001).

The app keeps a SHA-256 prefix of the object id, never the id itself. Conversations are partitioned by it, and approvals are audited with it.

Validating a token in the app was rejected: Easy Auth already does it in front of the app, and "external requests aren't allowed to set these headers, so they're present only if set by Container Apps" (Learn, "Authentication and authorization in Azure Container Apps", 2025-12-04). Ingress must therefore reach the app only through Easy Auth, which phase 7's Bicep ensures.

### One Cosmos DB document per conversation, not `CosmosHistoryProvider`

The build prompt named `CosmosHistoryProvider` for the conversations. Phase 5 measured why it cannot carry an approval across requests:
- **The approval needs the session.** Agent Framework 1.23 binds an approval response to the approval request it recorded in the session's state (`tool_approval`). Without that state, it drops the response with a warning.
- **The provider stores only messages.** Every request builds a new `AgentSession`, so the state would have to live in a second document anyway.

**The decision:** the conversation is the serialized session, `AgentSession.to_dict()`, in one document. It has the session id as its id and the owner's hash as its partition key (`/owner`), and it carries a title. The agent keeps its default in-memory history in that session.
- **One document.** Deletion (REQ-10) is one `delete_item`, and the 30-day expiry is the container's default TTL (phase 7).
- **Ownership is the partition.** Another user's id is simply not found: a 404, with no extra check.
- **Measured.** With the real `gpt-5-mini` and the Cosmos DB emulator on 2026-10-31: a planner's question, a follow-up that used the stored history, an owner's `start_promotion` approved in a second request that returned the shadow card, and a deletion. Each request built a new agent from the stored session.

The limit is the 2 MB document. A long conversation of 50 turns with tool results is about 200 KB.

`CosmosCheckpointStorage` is still used for the promotion workflow (ADR-009).

### KPI events are Application Insights custom events from the logging API

This settles the build prompt's **NOT VERIFIED** custom-events API.
- **Learn** ("Add and modify OpenTelemetry", updated 2026-09-11): a log record with the attribute `microsoft.custom_event.name` becomes a `customEvents` row with that name. The page now shows the Microsoft OpenTelemetry Distro, but the attribute is the same.
- **The installed package:** `azure-monitor-opentelemetry` 1.8.11 and its exporter 1.0.0b58 read the same attribute (`_MICROSOFT_CUSTOM_EVENT_NAME`).

`app/telemetry.py` sends every event through the `trainyard` logger. `configure_azure_monitor` gets `DefaultAzureCredential`, so ingestion uses Entra ID, and `enable_trace_based_sampling_for_logs=False`, so the default request sampling never drops a KPI event.

| Event | Sent by | Properties |
|---|---|---|
| `retrain_completed` (KPI-1) | the timer, once per finished pipeline run | `pipeline_job`, `duration_minutes`, `model` |
| `model_evaluated` (KPI-3) | the timer, the same run | `pipeline_job`, `recall_7d`, `precision_7d` |
| `model_promoted` (KPI-2, KPI-4) | the workflow, at 100 % | `model`, `drift_to_promotion_hours` when the monitor had breached |
| `model_rolled_back` (KPI-4) | the workflow, in the canary or the window | `model`, `reason` |
| `feedback_given` (KPI-5) | `POST /api/feedback` | `conversation`, `helpful` |
| `approval_given` (audit, threat model) | every tool approval and card decision | `approver` (hash), `step`, `model`, `decision` |

`tests/` attaches an in-memory OpenTelemetry exporter to the same logger and checks each event and its properties.

### Dependencies fail clearly

| Failure | Answer |
|---|---|
| The language model throttled (429 after the SDK's retries) | an `error` event in the stream with status 429, and `Retry-After` from the service when it sends one |
| The language model down or timed out | an `error` event with status 503: "The language model is unavailable; try again in a minute." |
| Azure Machine Learning or Cosmos DB down or throttled | HTTP 503 or 429, "A Trainyard service is unavailable; try again in a minute.", with `Retry-After` |

- **Timeouts and retries are the SDKs'.** The OpenAI client of `FoundryChatClient` has a 60-second timeout and 3 retries, which honour `Retry-After`. The Cosmos DB client has a 15-second timeout and its own throttling retries.
- **The platform's contract.** Phase 8's `Platform` raises `azure.core` `AzureError` for every Azure failure, which these handlers turn into the answers above.
- **The stream.** The chat streams Server-Sent Events with FastAPI's own `EventSourceResponse`. Once the stream has started, a failure arrives as an `error` event, because the status line has already been sent.

## State

- **Implemented and tested** (`tests/test_api.py`): sign-in and roles, the conversation round trip and its deletion, the feedback event, an owner's promotion through the chat, and a down or throttled model, endpoint and store.
- **Run locally** against the emulator and the real model, as above.
- **Declared in Bicep** (phase 7, validated with `what-if`): Easy Auth on the Container App with `RedirectToLoginPage`, the token store off and only `/healthz` excluded; the `conversations` container with partition key `/owner`, a 30-day default TTL and an index on `_ts` only.
- **Pending:** `connect()`, the Azure wiring with `DefaultAzureCredential`, first runs in staging in phase 8, together with Easy Auth's sign-in.

## Consequences

- The web (phase 6) reads `/api/me` for the roles and the display name, the `name` claim of the same header, which the app returns and never stores. It renders the `approval`, `text`, `error` and `done` events; `done` carries the promotion card for a model owner. An approval card answers in a new request, as Agent Framework expects (guide 5.1). While a canary card is open, the web reads `GET /api/promotion` every minute (ADR-009).
- The same app serves the built web from `web/dist`, after the API routes, so one Container App behind Easy Auth serves both.
- A request that changes the promotion never waits for the canary (ADR-009).
- If Agent Framework adds session state to `CosmosHistoryProvider`, this store can be replaced; the documents would not migrate, but they expire within 30 days.
