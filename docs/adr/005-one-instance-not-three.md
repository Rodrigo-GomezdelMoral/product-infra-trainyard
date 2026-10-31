# ADR-005 · One DS1_v2 instance per endpoint, not three

**Status:** accepted · **Date:** 2026-10-31

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

## Consequences

- A platform update or a failed instance can cost minutes of availability. The endpoint 5xx alert and the workbook's SLA tile show it.
- **Never run blue/green in both environments at once** (`OPERATIONS.md`): the quota holds one pair.
