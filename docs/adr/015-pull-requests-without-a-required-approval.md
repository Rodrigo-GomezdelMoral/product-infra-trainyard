# ADR-015 · Pull requests to `main` without a required approval

**Status:** accepted · **Date:** 2026-10-30

## Context

The AI-300 guidance on triggering workflows protects `main` with two settings: *require a pull request before merging* and *require approvals*. This repository has a single author, and GitHub never counts a pull request author's own approval. With no bypass actors on the ruleset, a required approval would make every merge to `main` impossible.

## Options

1. **A pull request with zero required approvals**, no bypass actors.
2. **One required approval, with the author as a bypass actor.** Every merge would bypass the ruleset, so the rule would protect nothing.
3. **One required approval from a second account or a bot.** The approval would be a formality with no independent reviewer behind it.

## Decision

**Option 1.** The ruleset `protect-main` keeps everything that does not depend on a second person:

- no direct pushes: every change reaches `main` through a pull request from a `feature/` branch;
- no force pushes and no deletion of `main`;
- no bypass actors, the author included;
- every pull request runs `ci.yml`: lint, format, types, tests, budgets and the identifier scan.

Production is protected separately: the `production` environment deploys only from `v*` tags and only after the owner approves the deployment.

## Consequences

- Review is the author reading the pull request. Each pull request body carries the evidence that review needs: the phase summary, real counts against budgets, and each requirement with its test and live evidence.
- Merging relies on the author seeing CI green. The `quality` job can become a required status check once it has run on `main`.
- If a second maintainer joins, raise the required approvals to one and add a `CODEOWNERS` file.
