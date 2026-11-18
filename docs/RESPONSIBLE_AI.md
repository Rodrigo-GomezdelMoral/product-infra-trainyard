# Responsible AI impact assessment

Trainyard's impact assessment follows the sections of the Responsible AI Impact Assessment Template and the goals of the [Microsoft Responsible AI Standard](https://www.microsoft.com/ai/principles-and-approach), together with the responsible AI guidance of the [Azure Well-Architected Framework](https://learn.microsoft.com/azure/well-architected/) for [AI workloads](https://learn.microsoft.com/azure/well-architected/ai/responsible-ai). A model card for the failure-risk model is at the end. **All data in this repository is synthetic** (`data/README.md`).

State on 2026-11-04: deployed to staging since 2026-11-01 and to production since `v1.0.0` (2026-11-03, 22:26 UTC), each environment serving one gated model. The evaluation is in `docs/evaluation.md`. The drift monitor has never completed a run in either environment: REQ-04's monitor is not measured yet (ADR-010).

## 1. System information

| | |
|---|---|
| **System name** | Trainyard |
| **Lifecycle stage** | deployed: staging since 2026-11-01, production since 2026-11-03 (`v1.0.0`) |
| **Description** | A weekly, explained list of the trains most likely to suffer an air production unit (APU) failure within 7 days, and a governed way to retrain, compare, promote and roll back the model behind it |
| **Purpose** | Put the workshop's limited inspection capacity, 6 units a week by default, on the units most likely to fail, and make every model change traceable and approved |
| **Features** | a LightGBM failure-risk model served by a managed online endpoint; per-unit explanations from the model's exact feature contributions; a chat agent on `gpt-5-mini` that chooses tools and writes the explanation; a training pipeline with a gate; a promotion workflow (shadow, canary, promotion, rollback) with the model owner's approvals; daily drift and data-quality monitoring |
| **Geography and language** | one regional rail operator; English; data at rest in Sweden Central |
| **Deployment mode** | an internal web application behind Microsoft Entra ID sign-in, with two app roles |

**Intended uses**
1. A maintenance planner asks which trains to inspect this week, and why.
2. A model owner retrains the model, compares the challenger with the champion, and approves or rolls back each promotion step.

## 2. Intended uses

**Goals of the Responsible AI Standard that apply:**
- *Impact assessment (A1):* this document, which the model owner reviews with each phase's pull request and again before `v1.0.0` (section 5).
- *Oversight of significant adverse impacts (A2):* section 3 finds that no sensitive-use trigger applies and gives, for each failure, its impact and how it is detected. The detection of a drifted model by the daily monitor is not measured yet: no monitor run has completed in either environment (ADR-010).
- *Fit for purpose (A3):* each intended use below states its fitness for purpose. A model serves only after a gate of recall of at least 0.80 at precision of at least 0.60 on the most recent matured weeks, and section 3 lists the uses that are out of scope or unsupported.
- *Data governance and management (A4):* section 4: a synthetic fleet feed; no personal data in the telemetry or the prompts; conversations under a hash of the user's object id, which expire after 30 days and can be deleted at any time (REQ-10); production data collected by the endpoint that never crosses environments (ADR-002, ADR-008).
- *Human oversight and control (A5):* the model never changes by itself. Every change tool waits for the model owner's approval, a `Reader` never receives those tools, a failed canary rolls back automatically, and the owner can roll back in one step during the window (ADR-009).
- *System intelligibility for decision making (T1):* each answer gives the top contributing signals and the model version, and every registered version carries its git commit, data version, pipeline job, gate decision and metrics (the model card's lineage).
- *Communication to stakeholders (T2):* this document, with its known limitations and its model card, and the README.
- *Disclosure of AI interaction (T3):* the interface discloses the AI in its own text: the empty state opens with "An AI assistant for this week's train inspections" and the message box reads "Ask the AI assistant about the fleet or the model".
- *Quality of service (F1):* applied to the two train series, because the system makes no decision about people: the gate requires a recall of at least 0.70 in every series. Series B's recall is judged on few events (section 3).
- *Failures and remediations (RS2):* section 3 lists each failure with its impact and its detection; the remediations are the canary's automatic rollback, the one-step rollback during the window and the runbook (section 5).
- *Ongoing monitoring, feedback and evaluation (RS3):* `eval/` on every pull request that can change the agent, KPI-3 on matured labels in every training run, and the KPI-5 feedback. The daily monitor of data drift, prediction drift and data quality is defined but not measured yet: no run has completed in either environment, and the schedule is disabled (ADR-010).

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
  - conversations hold only a 16-character SHA-256 prefix of the user's object id, never the id itself, and their text; they expire after 30 days, and can be deleted at any time (REQ-10);
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
| A bad promotion | shadow on mirrored traffic, a 10 % canary with an automatic health check and rollback, one-step rollback during the window | `test_canary_health_rollback`, `test_shadow_step` | tested with doubles; live in staging on 2026-11-03 (rollback, canary, promotion; ADR-009) |
| Drift going unnoticed | a daily `MonitorSchedule` with data drift, prediction drift and data quality; an alert; the workbook; meanwhile, KPI-3 on matured labels in every training run and `model_status`, which never reports drift from a run that did not complete | ADR-010; production's first run (2026-11-04, 03:15 UTC) never started its Spark steps and was cancelled, and the schedule is disabled | not measured yet: no monitor run has completed in either environment, a platform limitation documented in ADR-010 |
| Over-reliance | explanations with the top contributing signals and the model version; mandated inspections untouched; Trainyard prioritises and never decides | evaluation cases on explanations and on the mandated-inspection refusal | tested against the real model |
| Harmful content in the chat | the shared deployment's guardrail policy `guardrail-chat` | the deployment's configuration, read on 2026-10-31 | configured on the platform |
| Prompt injection | change tools absent for a `Reader`; approvals for a model owner | four adversarial cases | tested against the real model |

**Goals that apply.** Section 2 lists the goals of the Microsoft Responsible AI Standard that this product meets, each with how. Beyond them, privacy and security rest on Entra ID sign-in, managed identities, no keys and data minimisation, and inclusiveness on WCAG 2.2 AA for the interface.

**Review.** The model owner reviews this assessment with each phase's pull request, and again before `v1.0.0`.

**Language model retirement.** `gpt-5-mini` version `2025-08-07` runs with `NoAutoUpgrade`. The Foundry Models API gives its inference retirement as 2027-07-13 (read on 2026-11-04; Learn's *Foundry Models lifecycle and support policy* names that API as the source). At retirement the deployment stops answering. The plan: by 2027-04-14, about 90 days before, the declared replacement is deployed beside it and `eval/` runs against it with the same 44 cases and thresholds; `CHAT_MODEL_DEPLOYMENT` moves to it through a release only if every check passes, and otherwise the release notes say which check failed.

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
