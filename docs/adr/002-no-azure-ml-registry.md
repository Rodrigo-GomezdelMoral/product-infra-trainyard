# ADR-002 · No Azure Machine Learning registry: promote code, not models

**Status:** accepted · **Date:** 2026-10-31

## Context

Staging and production each have their own workspace (ADR-004, SE:04). A model trained in staging could reach production in two ways: through an Azure Machine Learning registry shared by both workspaces, or by retraining in production with the code that staging rehearsed.

## Options

1. **An Azure Machine Learning registry.** It moves models, components and environments between workspaces. But it creates its own Premium container registry, about USD 50.7 a month at rest (Retail Prices API, Sweden Central, 2026-10-30), and a model that crossed environments was trained on staging data.
2. **Promote code.** Staging rehearses the pipeline on every merge that touches `ml/`, `app/domain/` or `data/`. The release registers the same components in production, with the release's version, and production trains on its own data. The model owner promotes inside each environment, in the product.

## Decision

**Option 2.** Models, data and identities never cross environments; the image does, by digest (ADR-007). REQ-01's lineage stays inside one workspace: model version, pipeline job, data asset version and git commit.

## State

- **Implemented:** `deploy.yml` and `release.yml` register the four components with the image's version, or the release's, through `.github/actions/ship`. Validated with `what-if` in both groups (phase 7).
- **Pending:** the first registration and pipeline run in staging (phase 8), and in production with `v1.0.0`.

## Consequences

- Production's first model needs a training run on production data, and its own approval.
- A model is never compared across environments: each environment's gate compares a challenger with its own champion on the same holdout.
