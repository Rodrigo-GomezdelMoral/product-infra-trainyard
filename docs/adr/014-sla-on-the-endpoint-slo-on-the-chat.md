# ADR-014 · An SLA on the inference endpoint, an SLO on the chat

**Status:** accepted · **Date:** 2026-10-31

## Context

Trainyard has two surfaces. The inference endpoint scores the fleet and is always on (ADR-004). The chat app is a Container App that scales to zero, so the first request after an idle period waits for a cold start. Its answers also depend on a shared language model deployment, whose capacity Trainyard does not control.

## Options

1. **An SLA on both.** A committed chat SLA would need a warm replica, which bills every hour at the idle rate (about EUR 10 a month, as priced for the sibling product Juriscope), and would still depend on a shared tokens-per-minute quota.
2. **An SLA on the endpoint and an SLO on the chat.**

## Decision

**Option 2.**

| | SLA | SLO | SLI |
|---|---|---|---|
| Inference availability | ≥ 99.5 % a month | ≥ 99.7 % | non-failed ÷ all requests in `AmlOnlineEndpointTrafficLog`; failed = 5xx, 408 (timeout) or 429 |
| Inference latency | p95 < 500 ms | p95 < 400 ms | `percentile(TotalDurationMs, 95)` per day; the `RequestLatency_P95` metric for alerts |
| Chat | none | p95 time to first event < 3 s warm; errors < 1 % | App Insights requests; Locust's chat scenario |

- **The workbook** (`infra/workbook.json`) computes each SLI from these sources. `tests/test_infra.py` keeps its queries on these definitions and on the events the app really sends.
- **Alerts:** metric alerts fire on endpoint 5xx and on `RequestLatency_P95` above 400 ms for 15 minutes.
- **The release gate:** Locust fails a scenario that misses the SLA, and `release.yml` refuses a tag whose commit lacks a successful `load-test/normal`, `load-test/peak` and `load-test/endurance`.

## State

- **Implemented and tested** (phase 7): the workbook, the alerts and the Locust gate, validated with `what-if`; the gate was run locally against a stub, passing and failing.
- **Pending:** the measured figures, with date, window and number of requests (phase 8).

## Consequences

- The chat's cold start is measured and stated in `OPERATIONS.md`, not hidden by a warm replica.
