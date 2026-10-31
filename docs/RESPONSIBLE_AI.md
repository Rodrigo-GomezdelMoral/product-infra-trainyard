# Responsible AI impact assessment

Trainyard, following the structure of Microsoft's Responsible AI Impact Assessment template, with a model card for the failure-risk model at the end. **All data in this repository is synthetic** (`data/README.md`).

State on 2026-10-31: the agent, the training pipeline, the gate and the scoring script are implemented and tested locally. Their evaluation is in `docs/evaluation.md`. Nothing is deployed yet; phases 8 and 9 deploy to staging and production.

## 1. System information

| | |
|---|---|
| **System name** | Trainyard |
| **Lifecycle stage** | development; staging and production deployment follow in phases 8 and 9 |
| **Description** | A weekly, explained list of the trains most likely to suffer an air production unit (APU) failure within 7 days, and a governed way to retrain, compare, promote and roll back the model behind it |
| **Purpose** | Put the workshop's limited inspection capacity, 6 units a week by default, on the units most likely to fail, and make every model change traceable and approved |
| **Features** | a LightGBM failure-risk model served by a managed online endpoint; per-unit explanations from the model's exact feature contributions; a chat agent on `gpt-5-mini` that chooses tools and writes the explanation; a training pipeline with a gate; a promotion workflow (shadow, canary, promotion, rollback) with the model owner's approvals; daily drift and data-quality monitoring |
| **Geography and language** | one regional rail operator; English; data at rest in Sweden Central |
| **Deployment mode** | an internal web application behind Microsoft Entra ID sign-in, with two app roles |

**Intended uses**
1. A maintenance planner asks which trains to inspect this week, and why.
2. A model owner retrains the model, compares the challenger with the champion, and approves or rolls back each promotion step.

## 2. Intended uses

### Intended use 1: prioritising this week's inspections

**Fitness for purpose.** The customer loses about 5 APU failures a month at about €15,000 each (the customer's figures, `PRODUCT.md`). A list that puts the right units first within a fixed inspection budget addresses that directly. The model's gate requires recall of at least 0.80 at precision of at least 0.60 on the most recent matured weeks. Any number in the answer comes from a tool, never from the language model, and `eval/` enforces this on every pull request that can change it.

**Stakeholders**

| Stakeholder | Role | Benefit | Possible harm |
|---|---|---|---|
| Maintenance planners | direct users (`Reader`) | a ranked, explained list in seconds, instead of reading telemetry | over-reliance on the list; deprioritising a unit the list ranks low |
| Workshop technicians | indirect, act on the list | inspections that find real wear | wasted inspections on false alarms |
| Passengers | indirect | fewer stranded trains and cancellations | a missed failure leaves a train stranded |
| The operator | system owner | fewer penalties and tows; an auditable model | decisions made on a drifted model |

### Intended use 2: governing the model

**Fitness for purpose.** A model cycle takes the ML team 22 to 44 hours today (the customer's figure), so the model is retrained once a quarter and nobody notices drift. Trainyard runs the cycle as a pipeline in under 2 hours and keeps the model owner's time to two approvals. The model never changes by itself.

**Stakeholders.** The model owner (`ModelApprover`) is the direct user. Planners and technicians are affected by every promotion.

| Benefit | Possible harm |
|---|---|
| retraining in hours, with lineage from every score back to its data, job and commit | a promotion that degrades recall in production |
| shadow and canary evidence before users are affected | approval fatigue: approving without reading the comparison |

## 3. Adverse impact

**Restricted and unsupported uses.**
- **Out of scope:** replacing mandated maintenance, or making any safety decision. The agent's instructions say so, and the evaluation includes a request to skip a mandated inspection, which must be refused.
- **Unsupported:** real fleets, other failure modes, live sensor streams, several customers, and any automatic promotion (`PRODUCT.md`, *Won't*).

**Known limitations**
- **Synthetic data.** Every simulated failure has a 6 to 12 day precursor, so the model looks better than it would on a real fleet (`data/README.md`).
- **One failure-mode family.** Air leaks and valve wear are modelled; oil, motor, electrical and sensor faults are not.
- **Few events in Series B.** Series B's recall is judged on few events, so one missed failure can fail the gate (ADR-003).
- **Run-to-run variation.** The chat's language model varies between runs. Its numbers do not, because they come from tools.

**Potential impact of failure**

| Failure | Impact | Detection |
|---|---|---|
| A missed failure (false negative) | a stranded train, a tow, cancellations | KPI-3 recall on matured labels; the gate on every retrain |
| A false alarm | an inspection of a healthy unit | KPI-3 precision; the budget caps it at 6 units a week |
| A drifted model, such as after the `firmware-b` scenario | rankings silently worse | the daily monitor; an alert to the action group; the workbook |
| A wrong number in a chat answer | a planner acts on a figure the model never produced | `grounded` and `facts` in `eval/`, at 100 % and 90 % |

**Potential impact of misuse**
- **A `Reader` tries to promote or roll back,** including by prompt injection. The change tools are filtered out on the server before the model sees them (`test_reader_cannot_promote`, and four adversarial evaluation cases).
- **A model owner approves without reading.** Each card shows the comparison or the health check it asks about. A failed canary rolls back automatically.

**Sensitive uses.** None of the sensitive-use triggers applies:
- no consequential decision about a person;
- no risk of physical or psychological injury from the system's own action, because it only prioritises inspections and mandated maintenance stays untouched;
- no threat to human rights.

## 4. Data requirements

- **Training and scoring data:** a synthetic fleet feed. 40 units send 10-minute aggregates of the MetroPT-3 signal schema: seven analogue signals (TP2, TP3, H1, DV_pressure, Reservoirs, Oil_temperature, Motor_current) and six digital ones. The feed comes from a seeded degradation process. MetroPT-3 is cited as the schema reference; its data is not used.
- **Personal data:**
  - telemetry holds none;
  - conversations hold only the user's object id and their text, expire after 30 days, and can be deleted at any time (REQ-10);
  - prompts carry no personal data, so the Global Standard deployment may process them in any region (`PRODUCT.md`).
- **Production data collected by the endpoint:** the model's inputs and outputs. They are stored in that environment's workspace storage and never cross environments (ADR-002, ADR-008).

## 5. Summary of impact

This summary follows the four stages of Microsoft's guidance for responsible generative AI:
- **map:** the harms are mapped in sections 2 and 3;
- **measure:** they are measured by the gate and by `eval/`;
- **mitigate:** the mitigations are below;
- **operate:** monitoring, alerts, the runbook and this review keep them in check.

| Potential harm | Mitigation | Evidence | State |
|---|---|---|---|
| Missed failures | a gate on recall overall and per series; KPI-3 on matured labels | `test_gate_refuses_worse`; ADR-003's holdout | tested locally |
| Wasted inspections | operating point within the inspection budget at precision ≥ 0.60 | ADR-003 | tested locally |
| Invented or misattributed numbers | numbers only from tools; per-unit checks | `eval/`, `test_numbers_match_tools` | tested against the real model |
| Unauthorised model changes | role filtering on the server; `always_require` approval on every change tool | `test_reader_cannot_promote`, `test_retraining_waits_for_approval`, `held` at 100 % | tested against the real model |
| A bad promotion | shadow on mirrored traffic, a 10 % canary with an automatic health check and rollback, one-step rollback during the window | `test_canary_health_rollback`, `test_shadow_step` | tested with doubles; live in phase 8 |
| Drift going unnoticed | a daily `MonitorSchedule` with data drift, prediction drift and data quality; an alert; the workbook | phase 8 | pending |
| Over-reliance | explanations with the top contributing signals and the model version; mandated inspections untouched; Trainyard prioritises and never decides | evaluation cases on explanations and on the mandated-inspection refusal | tested against the real model |
| Harmful content in the chat | the shared deployment's guardrail policy `guardrail-chat` | the deployment's configuration, read on 2026-10-31 | configured on the platform |
| Prompt injection | change tools absent for a `Reader`; approvals for a model owner | four adversarial cases | tested against the real model |

**Goals that apply** (Microsoft Responsible AI Standard):
- **Accountability:** A1 impact assessment (this document), A2 oversight of significant adverse impacts (monitoring and alerts), A3 fit for purpose (sections 2 and 3), A4 data governance (section 4), A5 human oversight and control (approvals and rollback).
- **Transparency:** T1 intelligibility for decision making (explanations and lineage), T2 communication to stakeholders (this document and the README), T3 disclosure of AI interaction (the interface presents the chat as an AI assistant, phase 6).
- **Fairness:** F1 quality of service, applied to the two train series as the gate's per-series recall floor. The system makes no decisions about people, so F2 and F3 do not apply.
- **Reliability and safety:** RS1 guidance (`OPERATIONS.md`, phase 7), RS2 failures and remediations (rollback, runbook), RS3 ongoing monitoring, feedback and evaluation (monitor, KPI-5 feedback, `eval.yml`).
- **Privacy and security, and inclusiveness:** Entra ID, managed identities, no keys, data minimisation, and WCAG 2.2 AA for the interface (phase 6).

**Review.** The model owner reviews this assessment with each phase's pull request, and again before `v1.0.0`.

## Model card: `trainyard-risk`

| | |
|---|---|
| **Model** | LightGBM `LGBMClassifier` (300 trees, 15 leaves, deterministic, one thread), with Platt scaling fitted on the validation window |
| **Output** | the probability that a unit's APU fails within 7 days, and the top 3 contributing signals from the model's exact per-feature contributions (`pred_contrib`) |
| **Input** | one row per unit per day: a 7-day window turned into features by `ml/features.py`, the same function in training and in the app (`test_feature_parity`). The features are series, observed days, compressor duty while parked and in service, the change in duty over 2 days, time below the cut-in pressure and below 7 bar, reservoir pressure, oil temperature (mean and peak), and motor current |
| **Label** | a failure within the next 7 days |
| **Split** | by time, never at random. The last 56 days of matured rows are the holdout, the 56 days before them are validation, and the rest is training, with a 7-day gap between parts |
| **Operating point** | the lowest threshold on validation at which the weekly distinct flagged units stay within the inspection budget and precision is at least 0.60 |
| **Gate** | recall ≥ 0.80, precision ≥ 0.60, every series' recall ≥ 0.70, and at most 0.02 recall below the champion on the same holdout (`eval/thresholds.yaml`) |
| **Latest result** | 2026-10-31, a year of synthetic feed. Holdout recall 0.899 and precision 0.873; Series A 0.919 and Series B 0.714 (5 of 7 positives); at most 3 units flagged in any week. Gate passed (ADR-003) |
| **Lineage** | every registered version is tagged with its git commit, data asset and version, pipeline job, gate decision and metrics. The champion is the version serving 100 % of live traffic (ADR-009) |
| **Intended use** | prioritising APU inspections for this fleet |
| **Not for** | safety decisions, mandated maintenance, other fleets or failure modes without retraining and a new assessment |
| **Caveats** | synthetic data with clean precursors; one failure-mode family; few Series B events; no feedback from inspections into the feed |
