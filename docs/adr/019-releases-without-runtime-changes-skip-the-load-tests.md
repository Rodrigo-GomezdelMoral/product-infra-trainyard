# ADR-019 · Releases without runtime changes skip the load tests

**Status:** accepted · **Date:** 2026-11-02

## Context

`release.yml` promotes the image that staging runs for the tag's commit, and only if that commit has successful `load-test/normal`, `load-test/peak` and `load-test/endurance` statuses (REQ-07, REQ-08). The three scenarios take about 40 minutes of staging and bill the endpoint and the app for that time. Every merge to `main` redeploys staging and creates a new commit, so a release that changes only the web client, the documentation or a workflow would have to run all three again, although the endpoint, the app's Python, the Bicep and the ML code are the ones the load tests measured.

## Options

1. **Load tests on every release.** Safe, but a fix to a README or a web label costs 40 minutes and the endpoint's time, and the habit invites skipping releases.
2. **A manual override input.** The owner decides each time; nothing records why a release skipped the tests.
3. **An exemption by path, against the last release that reached production.** The workflow lists the paths changed since that release and requires the load tests as soon as one of them is outside the exempt set.

## Decision

Option 3, the owner's decision. The `verify` job of `release.yml`:

- still requires the `staging-image` status: the tag's commit was deployed to staging on merge, and production takes that digest;
- finds the previous release: the latest published release, not a draft or a pre-release, published before this tag, whose `release.yml` run on the `release` event succeeded, so it reached production;
- lists `git diff --name-only` between that release's tag and the tag's commit;
- exempts only `web/*`, `docs/*`, `.github/*` and `*.md`; any other path, or no earlier release in production, requires the three `load-test/<scenario>` statuses as before.

The first release, `v1.0.0`, always needs the load tests on its commit.

## Consequences

- **The comparison is with production, not with the last tag.** A release that failed or was never approved does not count, so its runtime changes still need the load tests in the next release.
- **The web client is exempt, and the app serves it.** A change in `web/` ships inside the same image, but it changes only static files under `web/dist`; the API, the endpoint and the scaling are unchanged. A change to `web/` that needs the backend changes Python as well and so needs the load tests.
- **Workflows are exempt.** A change to `.github/` can change how a deployment runs, not what it deploys; `deploy.yml` still deploys it to staging, and the release still requires the `staging-image` status.
- **The check needs history.** The job checks out the repository with full history and tags, without persisted credentials, and reads the workflow runs with `actions: read`.
- The job log lists every changed path as `exempt` or `runtime`, so the decision is visible in the release run.
