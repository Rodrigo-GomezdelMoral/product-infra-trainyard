# ADR-005 · One DS1_v2 instance per endpoint, not three

**Status:** accepted · **Date:** 2026-10-31 · **Revised:** 2026-11-03 (capacity bound)

## Context

Learn recommends at least three instances for a highly available online deployment. Microsoft's real-time scoring commitment (99.9 %, consolidated SLA, October 2026) sets no minimum instance count. REQ-07 commits 99.5 % a month, about 3.6 hours of downtime. The Azure Machine Learning quota in Sweden Central is 6 DSv2 cores, and one instance reserves `ceil(1.2 × 1) × 1 = 2` cores (Learn, how-to-manage-quotas).

## Options

1. **Three instances.** About USD 99 a month more per environment. Three instances reserve 6 cores, the whole DSv2 quota, with no room for the other environment or a blue/green pair.
2. **One instance with autoscale.** Autoscale needs headroom in the same quota and adds nothing at Trainyard's load.
3. **One instance, fixed.**

## Decision

**Option 3.** `instance_count: 1`, no autoscale. The quota then fits staging (2 cores), production (2) and one blue/green pair (2). Recovery comes from the platform: an unhealthy instance is replaced, and a promotion keeps the previous deployment until the owner closes the window.

## State

- **Decided.** The promotion workflow creates the deployments in phase 8, where Locust's four scenarios measure whether one instance meets REQ-07 and REQ-08.
- **Capacity bound, decided by the owner on 2026-11-03.** One instance stays, and REQ-07, REQ-08 and their SLA rows hold up to 5 requests a second of 40 rows. The peak test of 2026-11-03 measured the instance at about 7 such requests a second, with p95 375 ms and no failures at about 5 a second; 50 users at about 26 a second got 66 % `429 too_many_pending_request`. A second instance does not fit the DSv2 quota beside the other environment and a blue/green pair, and a bigger size would change the cost and the quota of both environments. The peak scenario is now 50 users at one request every 10 seconds each, about 5 a second at the endpoint (each fleet request scores once); stress keeps ramping to find the breaking point.

## Consequences

- A platform update or a failed instance can cost minutes of availability. The endpoint 5xx alert and the workbook's SLA tile show it.
- **Concurrency.** The default `max_concurrent_requests_per_instance` of 1 rejects a second overlapping request with `429 max_concurrent_requests_exceeded`: the normal load test on 2026-11-02 got 6 of them in about 785 requests at the endpoint (4 of the load test's 629, and 2 of the app's fleet calls), over REQ-07's 0.5 %, at a p95 of 179 ms for the rest. Each deployment now runs `WORKER_COUNT` 2 with up to 4 concurrent requests (Learn, online deployment schema: with the inference server, `WORKER_COUNT` sets how many requests the model serves at once; a limit above it can raise latency, one too low rejects requests with `429`). On one vCPU, a burst of up to 4 then waits about 100 ms per request ahead of it instead of failing. Load tests in staging measure it again (`OPERATIONS.md`). Deployments created before this change keep the old setting until they are replaced.
- **Never run blue/green in both environments at once** (`OPERATIONS.md`): the quota holds one pair.
