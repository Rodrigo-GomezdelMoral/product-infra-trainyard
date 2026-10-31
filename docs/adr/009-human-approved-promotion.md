# ADR-009 · Human-approved promotion: shadow, canary, rollback; the champion is live traffic

**Status:** accepted · **Date:** 2026-10-31

## Context

REQ-03 asks to compare every challenger with the champion before it serves anyone, offline and on mirrored live traffic. REQ-05 asks that the model never change by itself: a 10 % canary with an automatic health check, a second approval for 100 %, an automatic rollback when the check fails, and a one-step rollback during the window.

Azure Machine Learning managed online endpoints already give blue and green deployments, a live traffic split and mirrored traffic of up to 50 %. They give no canary analysis and no automatic rollback.

## Options

1. **A GitHub Actions job per step,** approved through environment reviewers. The approval would sit away from the comparison the owner has to read. Each step would need a workflow run, and the 15-minute health check would hold a runner.
2. **MLflow stage tags or aliases** to mark the champion. These are a second source of truth that can disagree with the endpoint, and the pinned MLflow 2.22 has no reliable aliases against Azure Machine Learning (ADR-011).
3. **An Agent Framework workflow in the app** (`WorkflowBuilder`, `request_info`), checkpointed, with its approvals as cards in the chat. The champion is whatever serves 100 % of live traffic.

## Decision

**Option 3**, in `app/promotion.py`.

### The steps

| Step | What happens |
|---|---|
| **Compare** | Reads the challenger's metrics, which `evaluate` measured on the same holdout as the champion it was compared with. It stops if the challenger lost more than 0.02 recall, or was compared with a model that no longer serves 100 %. It refuses a version that is not registered, and it refuses to start when both slots are busy. |
| **First model** | One approval, then `blue` at 100 %. |
| **Shadow** | The free slot gets the challenger, with 0 % live and 20 % mirrored traffic. The card shows the offline metrics and both deployments' requests, failures, p95 and the challenger's agreement. On approval the shadow is read again with fresh numbers. It goes on only when the shadow is healthy and has at least 200 mirrored requests or 30 minutes; otherwise the card comes back with the fresh numbers. The wait is a gate, not a sleep: nothing has to stay alive for 30 minutes. |
| **Canary** | 10 % live, and the card returns at once: the canary is a gate, like the shadow. A one-minute timer in the API checks the new deployment against the SLOs: failed requests (5xx, 429, timeouts) above 0.3 %, or p95 at or above 400 ms. On the first failure, traffic goes back to 0 % at once, the monitor goes back to the champion and the challenger is deleted, with no approval in between. *Roll back* works at any moment. *Promote to 100 %* is enabled after 15 minutes and 15 healthy checks, and the promotion itself runs one more check first. |
| **Promote** | 100 %, and the monitor schedule points at the new deployment. The window stays open, with the old deployment ready for a one-step rollback, until the owner closes it. Closing deletes the old deployment and frees its quota. |

### Rules that hold across steps

- **Only the explicit forward word advances:** `approve`, `approve`, `promote` and `close`, step by step. Any other answer takes the safe path back to the champion; the `rollback` tool answers `rollback`. The timer's own word, `check`, reaches only a canary that is not ready yet; the API accepts only the four words and `rollback`.
- **A fresh workflow instance for every call.** Every superstep is checkpointed, and every decision runs a new workflow instance from the stored checkpoint, so no process holds a promotion in memory.
- **The open promotion is the head of the checkpoint chain:** the checkpoint that no other one follows, with a pending request or pending messages. `get_latest` cannot be used:
  - the checkpoints of one run can share a timestamp at the clock's resolution;
  - on Windows, all three checkpoints of a run had the same timestamp, so `get_latest` returned the entry checkpoint, which has no pending request;
  - Cosmos DB's `ORDER BY c.timestamp` has the same tie.
- **Interrupted runs.** If a replica stops in the middle of a step, the head keeps pending messages, and the next `resume()` or timer tick runs that step again; setting the traffic is idempotent. If it stops during a check, the head is still the canary card, and the next check repeats it. The API calls `resume()` at start-up, in the background, so a step that takes minutes never blocks the start.
- **The canary is counted twice.** Ready needs both 15 healthy checks and 15 minutes since the canary began. Missed ticks make the canary longer; two ticks in one minute cannot make it shorter. Once it is ready, the timer stops checking, so the checkpoint chain stays short (about 20 checkpoints per canary) and the superstep count stays far below 1,000. The endpoint's metric alerts cover the wait, and the promotion runs a last check.
- **Reading a card costs nothing.** When the head is waiting for a decision, `resume()` returns its card from the checkpoint without running the workflow. This matters because the superstep counter is restored from the checkpoint, so every run of a promotion adds to the same count. The limit is raised from 100 to 1,000 so that repeated early approvals in shadow cannot exhaust it.
- **One writer across replicas: a lease in Cosmos DB.** Every call that can advance a promotion (start, answer, resume, tick) first takes the lease document `promotion`, in partition `lease` of the checkpoint container, with a conditional write: create-if-absent when it does not exist, `If-Match` on its ETag when it has expired. It expires after 3 minutes, and a background task renews it every minute while the step runs; if a renewal fails, the step is cancelled, because another replica may hold the lease. Releasing it writes an expiry of zero. A replica that cannot take it answers "A promotion step is running", and so does a second call in the same process.
  - **Options rejected.** An `asyncio.Lock` holds only in one process, which is how the race was reproduced. A blob lease would add a storage dependency to the app. A stored procedure would move logic into the database. The checkpoint container already exists; a document in its own partition is invisible to `list_checkpoints(workflow_name="promotion")`, and `load()` queries by `checkpoint_id`, which the lease does not have.
  - **The lease also keeps the timer's cursor.** `reported`, the end time of the last pipeline run whose KPI events were sent, lives in the lease document, so `retrain_completed` and `model_evaluated` go out once, from one replica.
- **Missing evidence never advances.**
  - A challenger without the champion's metrics on the same holdout counts as not compared.
  - A shadow with no mirrored request is never ready, however long it has run.
- **Storage:** `CosmosCheckpointStorage(container_client=...)`.
  - **The Bicep creates the container,** with partition key `/workflow_name`. Its indexing policy must keep `/workflow_name`, `/timestamp` and `/checkpoint_id`, because the storage queries `ORDER BY c.timestamp`. `infra/modules/app.bicep` indexes exactly those three paths and excludes the rest (phase 7).
  - **No auto-creation.** In the installed 1.0.0b261015, a container client skips `create_database_if_not_exists` and `create_container_if_not_exists`, which Entra-only data-plane access forbids.
  - **Registered payload types.** `Plan` and `Card` are registered with `register_checkpoint_type`, as the restricted unpickler requires.

## State

**Implemented and tested; the Azure Machine Learning calls are pending (phase 8).**

- **Tests,** with `InMemoryCheckpointStorage` and `FileCheckpointStorage`:
  - the full path, with a fresh runner and a fresh storage object at every step;
  - an interruption between steps and one during a canary check, then resume;
  - the shadow gate;
  - the canary gate: an early *Promote* returns the card, a failed check rolls back, and *Roll back* works at any moment;
  - the first model;
  - a rollback in the window;
  - every refusal;
  - two concurrent starts in one process;
  - **the race the review reproduced** (`test_one_writer_across_replicas`): two replicas with their own storage objects over the same checkpoints and one lease. Only one chain opens. Of two concurrent answers, one gets "A promotion step is running". After the promotion, the second replica's rollback finds nothing to roll back, and the serving deployment is never deleted.
- **Independent review on 2026-10-31.** It found five defects, each reproduced:
  - the superstep counter could run out;
  - two concurrent calls could both open a chain;
  - a challenger without the champion's metrics raised and left the promotion stuck;
  - a shadow with no traffic counted as ready;
  - zero canary checks crashed.

  All five are fixed; the lease closes the race between replicas.
- **Measured on the Cosmos DB emulator on 2026-10-31.**
  - Phase 2: the full path, interruption and resume, through `CosmosCheckpointStorage` with a pre-created container, left 11 checkpoint documents.
  - Phase 5: the same race through two `CosmosCheckpointStorage` objects and the real `Lease`. One chain opened, one of two concurrent answers was refused, the stale replica's rollback found nothing to answer, and `green` kept 100 %. A second `take()` while the lease was held returned nothing, and a write with a stale ETag failed with 412.
- **In the API** (`app/main.py`): `GET /api/promotion` reads the card and `POST /api/promotion` answers it, both for the `ModelApprover` role only. The chat starts a promotion through the approved `start_promotion` tool.
- **KPI events and audit.** `model_promoted`, with `drift_to_promotion_hours` when the monitor had breached; `model_rolled_back`, for the canary and the window only, because stopping in shadow is not a rollback. Every decision sends `approval_given` with a hash of the approver's object id, the step, the model version and the word.

**Pending:**

| Piece | Phase |
|---|---|
| Azure Machine Learning behind `deploy`, `route`, `health`, `watch`, `delete` and `runs` | 8 |
| The checkpoint container in Bicep, which also holds the lease's partition | 7 |
| The whole flow live in staging | 8 |

## Consequences

- **Nothing long runs inside a request.** Applying 10 % returns the card at once, the timer checks it every minute, and the owner can roll back between checks.
- **A replica that scales to zero stops the timer.** The canary then waits at 10 % until the next request starts a replica, whose `resume()` and first tick continue it. While a canary card is open, the web reads `GET /api/promotion` every minute to refresh it (phase 6), which also keeps the replica awake. The endpoint's metric alerts on 5xx and p95 reach the action group in any case.
- **Never two promotions at once.** Only one promotion can be open per environment; the runner refuses a second one while the first has an unfinished head.
- **Blue/green in both environments at once is an operating rule, not code.** The DSv2 quota fits one blue/green pair (`CLAUDE.md`), and the workflow cannot see the other environment, so `OPERATIONS.md` (phase 7) states the rule. Closing the window deletes the old deployment and frees its quota.
- **The checkpoint container grows** by about 30 documents per promotion. It has no TTL, because an open window lasts as long as the owner keeps it open.
