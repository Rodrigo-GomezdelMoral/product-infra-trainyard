# ADR-005 · One DS1_v2 instance per endpoint, not three

**Status:** accepted · **Date:** 2026-10-31 · **Revised:** 2026-11-03 (capacity bound, confirmed by the release load tests)

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
- **Confirmed on 2026-11-03 by the release load tests** (from 19:09 UTC on commit `6d091cf`, only `green` serving model 4 with `WORKER_COUNT` 2; every figure from the endpoint's `AmlOnlineEndpointTrafficLog`), and the owner keeps the bound:
  - **Endurance holds 5 a second.** From 19:19:30 to 19:49:40 UTC: 9,680 requests, 5.38 a second, 0 failed, p50 156 ms, p95 399 ms. The p95 leaves about 20 % of margin under REQ-08's 500 ms (399 against 500), and it is the SLO's 400 ms almost exactly, so 5 a second is the bound and not a starting point.
  - **Normal:** 859 requests in 5 minutes, about 2.9 a second, 0 failed, p50 102 ms, p95 238 ms.
  - **Peak failed by bunching, not by capacity.** 600 requests in 114 s (5.3 a second on average), 97 × `429` (16 %), p50 684 ms, p95 992 ms. Its 50 users were spawned 10 a second, all within 5 s, and `constant_pacing(10)` keeps each user's requests 10 s apart, so the users stayed in step: each 10 s cycle sent its 50 requests in about 5 s, bursts of about 10 a second against an instance that queues 4. Peak now spawns 5 users a second, so the 50 users spread over the 10 s cycle and arrive at an even 5 a second, the load endurance held (`load-test.yml`).
  - **Stress breaks between 5 and 7 a second.** It ramps one user a second and stopped at about 35 users when Locust saw 2 of 187 scoring requests fail (1.07 %). At the endpoint it lasted under a minute, 20:06:10 to 20:06:59 UTC: 214 requests, 3 × `429` (1.4 %), p95 820 ms for that one minute. By 10 s: 1.0 a second (p95 247 ms), 4.2 (314 ms), 7.1 (649 ms, over 500 ms) and 7.4 (847 ms, the 3 × `429`). The latency SLA breaks at about 7 a second, the same as the diagnostic peak of 10:08, and the bound of 5 keeps a margin of about 2 a second.

## Consequences

- A platform update or a failed instance can cost minutes of availability. The endpoint 5xx alert and the workbook's SLA tile show it.
- **Concurrency.** The default `max_concurrent_requests_per_instance` of 1 rejects a second overlapping request with `429 max_concurrent_requests_exceeded`: the normal load test on 2026-11-02 got 6 of them in about 785 requests at the endpoint (4 of the load test's 629, and 2 of the app's fleet calls), over REQ-07's 0.5 %, at a p95 of 179 ms for the rest. Each deployment now runs `WORKER_COUNT` 2 with up to 4 concurrent requests (Learn, online deployment schema: with the inference server, `WORKER_COUNT` sets how many requests the model serves at once; a limit above it can raise latency, one too low rejects requests with `429`). On one vCPU, a burst of up to 4 then waits about 100 ms per request ahead of it instead of failing. Load tests in staging measure it again (`OPERATIONS.md`). Deployments created before this change keep the old setting until they are replaced.
- **Never run blue/green in both environments at once** (`OPERATIONS.md`): the quota holds one pair.
