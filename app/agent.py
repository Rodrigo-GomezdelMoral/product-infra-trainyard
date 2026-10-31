"""REQ-01, REQ-05, REQ-06: one agent that chooses tools and writes the explanation; every number comes from a tool."""

import json
from collections.abc import Iterable
from dataclasses import asdict
from typing import Annotated, Any

import pandas as pd
from agent_framework import Agent, SupportsChatGetResponse, tool

from app.domain.fleet import INSPECTION_BUDGET, explain, plan
from app.platform import Platform, Scores
from app.promotion import Promotions
from ml.features import HORIZON

APPROVER, MAX_TOKENS = "ModelApprover", 4000
INSTRUCTIONS = """You are Trainyard. You help a rail operator's maintenance planners decide which of the 40 electric
multiple units, EMU 2401 to EMU 2440, to inspect, by the risk that a unit's air production unit fails within 7 days.
You also help the model owner retrain, promote and roll back the model behind that risk.
- Use a tool for every fact. Copy each number exactly as the tool wrote it, with its unit. Never round, convert,
  add up or compute a number of your own.
- For this week's inspections call fleet_risk and answer with a Markdown table: rank, unit, series, 7-day failure
  probability and top signals. Then name the model version and the inspection budget.
- To explain one unit call explain_unit. For lineage, metrics, traffic or drift call model_status.
- Retraining, promotion and rollback happen only through their tools, after the model owner approves. If you do not
  have those tools, say that only a model owner can do it.
- Trainyard prioritises inspections. It never replaces mandated maintenance or a safety decision. Be brief."""


def dump(**facts: Any) -> str:
    return json.dumps(facts, ensure_ascii=False)


def pct(share: float) -> str:
    return f"{share:.0%}"


class Tools:
    def __init__(self, platform: Platform, promotions: Promotions) -> None:
        self.platform, self.promotions = platform, promotions

    async def scored(self) -> tuple[pd.DataFrame, Scores]:
        rows = await self.platform.week()
        return rows, await self.platform.score(rows)

    async def fleet_risk(self) -> str:
        """This week's inspection list: the units most likely to fail within 7 days, within the inspection budget."""
        rows, scores = await self.scored()
        week = plan(rows, scores.frame, scores.threshold)
        units = [
            {"rank": rank, **asdict(unit), "probability": pct(unit.probability)}
            for rank, unit in enumerate(week.units, 1)
        ]
        return dump(
            week_of=str(rows["as_of"].iloc[0].date()),
            model_version=scores.model,
            threshold=pct(scores.threshold),
            inspection_budget=INSPECTION_BUDGET,
            horizon_days=HORIZON.days,
            inspect=units,
            flagged_over_budget=week.over_budget,
        )

    async def explain_unit(self, unit: Annotated[int, "The unit number, for example 2417 for EMU 2417"]) -> str:
        """Why one unit is or is not at risk this week: its 7-day failure probability and top contributing signals."""
        rows, scores = await self.scored()
        if unit not in set(rows["unit"]):
            return dump(error=f"EMU {unit} sent no telemetry this week.")
        probability = float(scores.frame.loc[scores.frame["unit"] == unit, "probability"].iloc[0])
        return dump(
            unit=f"EMU {unit}",
            probability=pct(probability),
            flagged=probability >= scores.threshold,
            threshold=pct(scores.threshold),
            model_version=scores.model,
            signals=explain(rows, scores.frame, unit),
        )

    async def model_status(self) -> str:
        """Models with lineage (training job, data asset version, git commit), metrics, traffic, last monitor run."""
        endpoint = await self.platform.endpoint()
        traffic = {
            slot: {
                "model_version": version,
                "live": f"{endpoint.live.get(slot, 0)} %",
                "mirrored": f"{endpoint.mirror.get(slot, 0)} %",
            }
            for slot, version in endpoint.models.items()
        }
        models = [
            {"version": m.version, **{k: pct(v) for k, v in m.metrics.items()}, **m.tags}
            for m in await self.platform.models()
        ]
        return dump(traffic=traffic, registered_models=models, last_monitor_run=await self.platform.monitor())

    async def start_retraining(self) -> str:
        """Retrain: submit prepare, train, evaluate and register on the latest fleet data, on serverless compute."""
        return dump(**await self.platform.retrain())

    async def start_promotion(self, version: Annotated[str, "The registered model version, for example 3"]) -> str:
        """Start promoting a registered model: comparison, shadow, canary at 10 %, then 100 %, each step approved."""
        return dump(**asdict(await self.promotions.start(version)))

    async def rollback(self) -> str:
        """Roll back the promotion in progress: the previous model goes back to 100 % of live traffic."""
        return dump(**asdict(await self.promotions.answer("rollback")))


def build_agent(client: SupportsChatGetResponse[Any], tools: Tools, roles: Iterable[str]) -> Agent[Any]:
    allowed = [tool(tools.fleet_risk), tool(tools.explain_unit), tool(tools.model_status)]
    if APPROVER in roles:
        changes = (tools.start_retraining, tools.start_promotion, tools.rollback)
        allowed += [tool(change, approval_mode="always_require") for change in changes]
    options = {"max_tokens": MAX_TOKENS, "store": False, "reasoning": {"effort": "low"}}
    return Agent(client=client, instructions=INSTRUCTIONS, name="trainyard", tools=allowed, default_options=options)
