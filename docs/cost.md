# Cost

An estimate, not a measurement: Sweden Central, USD, Azure Retail Prices API on 2026-10-30, 730 hours a month. Phase 8 compares it with Cost Management per resource group, and phase 9 states the measured figures with their dates.

## Per environment, per month

| | Staging | Production |
|---|---|---|
| Endpoint, 1 × `Standard_DS1_v2` at USD 0.0679 an hour | 49.57 | 49.57 |
| Model monitor, daily, serverless Spark at USD 0.142 per vCore-hour (estimate: 2 × `standard_e4s_v3` nodes, 15 minutes) | 0 (on demand) | about 8.5 |
| Storage, Key Vault, Cosmos DB storage, the log alert (USD 0.50 at 15 minutes), ingestion under the free 5 GB | about 2 | about 3 |
| **At rest** | **about 52** | **about 61** |
| In use: training runs (`Standard_F2s_v2` at USD 0.097 an hour, about 30 minutes each), the chat (`gpt-5-mini`, USD 0.25 and 2.00 per million input and output tokens), the second deployment during a promotion (about USD 1.6 a day), Container Apps beyond the free grant (Germany West Central, ADR-017, one environment for both apps, ADR-018, at Sweden Central's prices; inter-region transfer USD 0.02 per GB) | about 4 | about 4 |
| **In use** | **about 56** | **about 65** |
| Budget in Bicep (alerts at 80 % actual and 100 % forecast), in the billing currency, EUR | 60 | 80 |

- **Free at rest:** Container Apps (scale to zero), the workspace, Cosmos DB serverless (storage only), serverless training compute, the workbook, the first 10 metric alert series.
- **Not Trainyard's:** the shared base's own idle cost, such as the Basic registry at USD 0.1666 a day.
- **The subscription** is Pay-As-You-Go with no spending limit: the budgets only alert.

## Measured

Cost Management, month to date on 2026-11-10 (EUR, the billing currency, about a day behind), per resource group: staging **16.25**, production **10.58**. Production's figure covers about a week, since its start on 2026-11-03.

By meter, month to date on 2026-11-04:

| Meter | Staging | Production |
|---|---|---|
| Endpoint compute (Dv2) | 5.14 | 0.32 |
| Blob storage | 0.56 | |
| IP Addresses (the workspace's public IP address) | 0.42 | 0.04 |
| Training compute (FSv2) | 0.15 | |
| Cosmos DB point-in-time restore (the restore drill's account, 2026-11-01) | 0.13 | |
| Image builds of the workspace environment (Edsv4) | 0.07 | 0.08 |
| Managed disks | 0.07 | |
| Other meters (Azure Monitor among them) | 0.07 | 0.08 |
| **Total** | **6.61** | **0.52** |

Two meters were missing from the estimate: the IP Addresses meter, a few cents a day per workspace, and the restore drill's one-off point-in-time restore charge. Production started on 2026-11-03 at 22:26 UTC, so its figure covers about one day.

## Unit costs

| Unit | Estimate | How |
|---|---|---|
| Per train, per month, in production | about USD 1.5 | production at rest ÷ 40 units |
| Per retraining cycle | about USD 0.05 of compute | four steps on one `Standard_F2s_v2` node, about 30 minutes |
| Per day of blue/green | about USD 1.6 | the second deployment's 24 hours |
| Per chat question | about USD 0.002 | about 1,500 input and 900 output tokens on `gpt-5-mini` |

The workbook's unit-cost tile shows these estimates next to the counted volumes; Cost Management holds the actuals.

## Switching cost off

Delete the endpoint deployments: the endpoint, the registered models and the data stay, and the promotion workflow redeploys. Disable the production monitor schedule. Two weeks with Azure switched on cost about USD 55 in total.

## Alternatives rejected on cost

- **An Azure Machine Learning registry:** about USD 50.7 a month more (ADR-002).
- **Three instances per endpoint:** about USD 99 a month more per environment (ADR-005).
- **A warm chat replica:** the chat carries an SLO, not an SLA (ADR-014).
