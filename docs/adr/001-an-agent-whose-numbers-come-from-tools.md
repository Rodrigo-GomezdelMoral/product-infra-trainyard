# ADR-001 · One agent, and every number from a tool

**Status:** accepted · **Date:** 2026-10-31

## Context

`azure-care-intelligence-platform` has no agent: its users press buttons on fixed views. Trainyard has two users who ask open questions about the same facts. A planner asks which trains to inspect this week and why one of them is on the list. A model owner asks where a score comes from, whether the model drifts, and wants to retrain, promote and roll back without leaving the conversation (REQ-01, REQ-05, REQ-06).

A language model in this loop brings two risks. It can invent or recompute a number that a planner then acts on. And a prompt, its own or injected, can try to change the model that serves the fleet.

## Options

1. **No agent.** A fixed inspection table and lifecycle buttons, as in care-intel. Safe, but every new question becomes a new screen, and approvals live apart from the explanation that justifies them.
2. **An agent that reads the data in its prompt** and answers from it. It is flexible, but the numbers in an answer are the model's arithmetic, and nothing stops it from acting on anything it can see.
3. **One agent that only chooses tools and writes the explanation.** Every number comes from a tool. The server decides which tools a user's agent has, and every tool that changes the model waits for a person.

## Decision

**Option 3**, in `app/agent.py`, with Agent Framework (`Agent`, `tool`) and `FoundryChatClient` on the shared `gpt-5-mini` deployment.

- **Six tools.** Three read: `fleet_risk`, `explain_unit` and `model_status`. Three change the model: `start_retraining`, `start_promotion` and `rollback`. The changing tools are declared with `approval_mode="always_require"`: the model can only propose them, and they run after the person approves.
- **Role filtering on the server.** `build_agent` builds the agent for each request with the tools of the caller's app roles. A `Reader`'s agent has no changing tool at all. If the model still calls one, the framework answers "Requested function not found" and nothing runs (measured with a scripted model and with the real one).
- **Display-ready tool outputs.** Probabilities, metrics and signals leave the tools already formatted as the planner reads them ("96%", "time below 8.2 bar 8.3%, fleet median 2.8%"). The model copies them instead of converting them. The instructions forbid rounding, converting, adding up or computing any number.
- **Numbers check.** Every number in an answer must appear in the tool outputs of that run, in the question or in the instructions. `tests/test_agent.py` applies the check; phase 4 moves it into `eval/`.
- **Model options:**
  - **Reasoning effort `low`.**
  - **`max_tokens` 4,000.** The largest answer measured used 879 output tokens, 384 of them reasoning.
  - **`store` off.** The Responses store would keep a second copy of every conversation outside Cosmos DB, beyond the reach of REQ-10's deletion.
- **Sessions.** The API (phase 5) runs every conversation with a session. With a session, a batch that mixes an approval tool with a read tool surfaces only the approval tool, and the read tool runs (measured). Without a session, the framework asks approval for the whole batch.
- **The endpoint's contract.** The endpoint returns a probability and per-feature contributions for each unit, plus the model version and its operating threshold. The threshold travels with the model, so every answer names the model that actually scored it (REQ-01). Phase 3 implements this contract in `ml/score.py`.

## State

**Implemented and tested.** CI runs the agent tests with a scripted model. In phase 2 the same tests could run against the real `gpt-5-mini` of the shared base when `FOUNDRY_PROJECT_ENDPOINT` was set, and 5 of 5 passed on 2026-10-31. Since phase 4, the live path is the agent evaluation (`eval/`, `docs/evaluation.md`): 43 cases with thresholds, run by `eval.yml` on every pull request that can change the agent. Its `facts` check adds the per-unit check promised below.

**Live runs, 2026-10-31.** Five scenarios, three rounds each, 15 runs in all, with the endpoint and Azure Machine Learning replaced by doubles:

| Measure | Result |
|---|---|
| Unmatched numbers in answers | 0 |
| Approval requests or traffic changes caused by a `Reader` asking, with an injection, to promote | 0 |
| Retraining requests stopped at an approval before anything was submitted | 3 of 3 |
| Fleet answers that kept the six ranked units in tool order, checked by the live test | 2 of 2 |

**Not deployed.** The doubles stand in for the endpoint (phase 3) and Azure Machine Learning (phase 8).

## Consequences

- **Latency must be streamed.** End to end and not streamed, the fleet answer took 6.8 to 14.0 s from a laptop: one tool call, two model calls and about 880 output tokens. Phase 5 streams it; phase 8 measures the SLO of a p95 time to first token under 3 s, warm.
- **An injected prompt from a `Reader` can only read.** In 2 of 3 rounds the injected promotion request made the model call `model_status` or `fleet_risk`, which is harmless.
- **The numbers check is about provenance, not correctness.** A number copied from the wrong unit's row would pass it; phase 4's evaluators add per-unit checks.
- **A model owner still decides.** The agent never changes traffic: promotion is the workflow of ADR-009, and each of its steps waits for the owner.
