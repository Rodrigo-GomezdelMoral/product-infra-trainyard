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
| **Canary** | 10 % live, checked every minute for 15 minutes against the SLOs: failed requests (5xx, 429, timeouts) above 0.3 %, or p95 at or above 400 ms. On the first failure, traffic goes back to 0 % at once, the monitor goes back to the champion and the challenger is deleted, with no approval in between. |
| **Promote** | 100 %, and the monitor schedule points at the new deployment. The window stays open, with the old deployment ready for a one-step rollback, until the owner closes it. Closing deletes the old deployment and frees its quota. |

### Rules that hold across steps

- **Only the explicit forward word advances:** `approve`, `approve`, `promote` and `close`, step by step. Any other answer takes the safe path back to the champion; the `rollback` tool answers `rollback`.
- **A fresh workflow instance for every call.** Every superstep is checkpointed, and every decision runs a new workflow instance from the stored checkpoint, so no process holds a promotion in memory.
- **The open promotion is the head of the checkpoint chain:** the checkpoint that no other one follows, with a pending request or pending messages. `get_latest` cannot be used:
  - the checkpoints of one run can share a timestamp at the clock's resolution;
  - on Windows, all three checkpoints of a run had the same timestamp, so `get_latest` returned the entry checkpoint, which has no pending request;
  - Cosmos DB's `ORDER BY c.timestamp` has the same tie.
- **Interrupted runs.** If a replica stops during the canary, the head keeps pending messages, and `resume()` runs that step again. Setting the traffic is idempotent and the 15-minute window restarts, so the canary is observed longer, never shorter.
- **Reading a card costs nothing.** When the head is waiting for a decision, `resume()` returns its card from the checkpoint without running the workflow. This matters because the superstep counter is restored from the checkpoint, so every run of a promotion adds to the same count. The limit is raised from 100 to 1,000 so that repeated early approvals in shadow cannot exhaust it.
- **One step at a time in a process.** A call that arrives while a step runs gets "A promotion step is running" instead of starting a second chain. Across replicas this lock does not hold (see Pending).
- **Missing evidence never advances.**
  - A challenger without the champion's metrics on the same holdout counts as not compared.
  - A shadow with no mirrored request is never ready, however long it has run.
- **Storage:** `CosmosCheckpointStorage(container_client=...)`.
  - **The Bicep creates the container,** with partition key `/workflow_name`. Its indexing policy must keep `/workflow_name`, `/timestamp` and `/checkpoint_id`, because the storage queries `ORDER BY c.timestamp`.
  - **No auto-creation.** In the installed 1.0.0b261015, a container client skips `create_database_if_not_exists` and `create_container_if_not_exists`, which Entra-only data-plane access forbids.
  - **Registered payload types.** `Plan` and `Card` are registered with `register_checkpoint_type`, as the restricted unpickler requires.

## State

**Implemented and tested.**

- **Tests,** with `InMemoryCheckpointStorage` and `FileCheckpointStorage`:
  - the full path, with a fresh runner and a fresh storage object at every step;
  - an interruption during the canary, then resume;
  - the shadow gate;
  - an automatic canary rollback;
  - the first model;
  - a rollback in the window;
  - every refusal;
  - two concurrent starts in one process.
- **Independent review on 2026-10-31.** It found five defects, each reproduced:
  - the superstep counter could run out;
  - two concurrent calls could both open a chain;
  - a challenger without the champion's metrics raised and left the promotion stuck;
  - a shadow with no traffic counted as ready;
  - zero canary checks crashed.

  Four are fixed, and the review's own reproductions now pass: 120 early approvals and 110 resumes no longer exhaust the counter. The race between replicas remains, as pending.
- **Measured on the Cosmos DB emulator on 2026-10-31.** The same full path, interruption and resume, through `CosmosCheckpointStorage` with a pre-created container, left 11 checkpoint documents.

**Pending:**

| Piece | Phase |
|---|---|
| Azure Machine Learning behind `deploy`, `route`, `health`, `watch` and `delete` | 8 |
| Hosting in the API | 5 |
| A single writer across replicas, such as a lease document in Cosmos DB taken with a conditional write. Without it, two replicas answering at once can open two chains, and a later rollback on the stale chain can delete the serving deployment (reproduced with two storage objects) | 5 |
| KPI events `model_promoted` and `model_rolled_back` | 5 |
| Approver audit, a hash of the approver's object id, the version and the step | 5 |
| The whole flow live in staging | 8 |

## Consequences

- **The canary's 15 minutes run inside the app,** driven by the request that approved the shadow. That is longer than a request should stay open, so phase 5 runs it as a background task and calls `resume()` at start-up.
- **The owner cannot stop a canary while its checks run.** Any answer during those 15 minutes gets "A promotion step is running"; only the automatic rollback acts. Phase 5 should consider a canary built like the shadow: a gate whose checks are driven by a one-minute timer in the API, so the owner could stop it at any moment and nothing long would run inside a request.
- **A stopped replica leaves the canary unchecked.** If the replica stops, the canary stays at 10 % without checks until `resume()` runs. The endpoint's metric alerts on 5xx and p95 still reach the action group.
- **Never two promotions at once.** Only one promotion can be open per environment; the runner refuses a second one while the first has an unfinished head.
- **Blue/green in both environments at once is an operating rule, not code.** The DSv2 quota fits one blue/green pair (`CLAUDE.md`), and the workflow cannot see the other environment, so `OPERATIONS.md` (phase 7) states the rule. Closing the window deletes the old deployment and frees its quota.
