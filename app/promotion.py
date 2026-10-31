"""REQ-03, REQ-05: the model promotion as a checkpointed workflow; each traffic change waits for the owner."""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from functools import partial
from typing import Any, Never

from agent_framework import (
    CheckpointStorage,
    Executor,
    Workflow,
    WorkflowBuilder,
    WorkflowCheckpoint,
    WorkflowContext,
    WorkflowRunResult,
    handler,
    register_checkpoint_type,
    response_handler,
)

from app.platform import Health, NotReadyError, Platform
from app.store import Lease
from app.telemetry import event

NAME, SLOTS, CHECK = "promotion", ("blue", "green"), "check"
MIRROR, CANARY, SHADOW_REQUESTS, SHADOW_MINUTES, MAX_RECALL_LOSS, MAX_SUPERSTEPS = 20, 10, 200, 30, 0.02, 1000
FORWARD = {"first": "approve", "shadow": "approve", "canary": "promote", "window": "close"}


@dataclass(frozen=True)
class Plan:
    challenger: str
    slot: str
    champion: str = ""
    live: str = ""


@dataclass(frozen=True)
class Card:
    step: str
    plan: Plan
    facts: dict[str, Any]


@dataclass(frozen=True)
class Status:
    outcome: str | None
    card: Card | None


BUSY = Status("A promotion step is running; try again in a minute.", None)

for kind in (Plan, Card):
    register_checkpoint_type(kind)


def ready(shadow: Health) -> bool:
    return (
        shadow.requests > 0 and shadow.ok and (shadow.requests >= SHADOW_REQUESTS or shadow.minutes >= SHADOW_MINUTES)
    )


def hours_since(moment: str) -> float:
    return (datetime.now(UTC) - datetime.fromisoformat(moment)).total_seconds() / 3600


class Step(Executor):
    def __init__(self, platform: Platform) -> None:
        super().__init__(id=type(self).__name__.lower())
        self.platform = platform

    async def go_live(self, plan: Plan, ctx: WorkflowContext[Plan, str]) -> None:
        breached = (await self.platform.monitor()).get("breached_at")
        await self.platform.route({plan.slot: 100} | ({plan.live: 0} if plan.live else {}), {})
        await self.platform.watch(plan.slot)
        hours = round(hours_since(breached), 2) if breached else None
        event("model_promoted", model=plan.challenger, drift_to_promotion_hours=hours)
        if plan.live:
            await ctx.send_message(plan)
        else:
            await ctx.yield_output(f"Model {plan.challenger} serves 100 % from {plan.slot}.")

    async def undo(self, plan: Plan, ctx: WorkflowContext[Any, str], why: str, rolled_back: bool = True) -> None:
        await self.platform.route({plan.live: 100, plan.slot: 0}, {})
        await self.platform.watch(plan.live)
        await self.platform.delete(plan.slot)
        if rolled_back:
            event("model_rolled_back", model=plan.challenger, reason=why)
        await ctx.yield_output(f"Model {plan.challenger} removed ({why}); model {plan.champion} serves 100 %.")


class Compare(Step):
    @handler
    async def start(self, version: str, ctx: WorkflowContext[Plan, str]) -> None:
        endpoint, models = await self.platform.endpoint(), {m.version: m for m in await self.platform.models()}
        free = [slot for slot in SLOTS if slot not in endpoint.models]
        if version not in models or not free:
            await ctx.yield_output(f"Model {version} cannot start: it is not registered or both slots are busy.")
            return
        live, challenger = endpoint.champion or "", models[version]
        plan = Plan(version, free[0], endpoint.models.get(live, ""), live)
        if not live:
            await ctx.request_info(Card("first", plan, challenger.metrics), str)
        elif challenger.tags.get("champion") != plan.champion or "champion_recall" not in challenger.metrics:
            await ctx.yield_output(f"Model {version} was not compared with model {plan.champion}: retrain first.")
        elif challenger.metrics.get("recall", 0.0) < challenger.metrics["champion_recall"] - MAX_RECALL_LOSS:
            await ctx.yield_output(f"Model {version} lost to model {plan.champion} on the same holdout.")
        else:
            await ctx.send_message(plan)

    @response_handler
    async def decide(self, card: Card, decision: str, ctx: WorkflowContext[Plan, str]) -> None:
        if decision != FORWARD[card.step]:
            await ctx.yield_output(f"Model {card.plan.challenger} was not deployed.")
            return
        await ctx.send_message(card.plan)


class Shadow(Step):
    @handler
    async def start(self, plan: Plan, ctx: WorkflowContext[Plan, str]) -> None:
        await self.platform.deploy(plan.slot, plan.challenger)
        if not plan.live:
            return await self.go_live(plan, ctx)
        await self.platform.route({plan.live: 100, plan.slot: 0}, {plan.slot: MIRROR})
        await self.ask(plan, ctx)

    async def ask(self, plan: Plan, ctx: WorkflowContext[Plan, str]) -> None:
        shadow, live = await self.platform.health(plan.slot), await self.platform.health(plan.live)
        offline = next(m.metrics for m in await self.platform.models() if m.version == plan.challenger)
        facts = {"offline": offline, "challenger": asdict(shadow), "champion": asdict(live), "ready": ready(shadow)}
        await ctx.request_info(Card("shadow", plan, facts), str)

    @response_handler
    async def decide(self, card: Card, decision: str, ctx: WorkflowContext[Plan, str]) -> None:
        if decision != FORWARD[card.step]:
            await self.undo(card.plan, ctx, "stopped in shadow", rolled_back=False)
        elif ready(await self.platform.health(card.plan.slot)):
            await ctx.send_message(card.plan)
        else:
            await self.ask(card.plan, ctx)


class Canary(Step):
    def __init__(self, platform: Platform, checks: int, minutes: float) -> None:
        super().__init__(platform)
        self.checks, self.minutes = checks, minutes

    @handler
    async def start(self, plan: Plan, ctx: WorkflowContext[Plan, str]) -> None:
        await self.platform.route({plan.live: 100 - CANARY, plan.slot: CANARY}, {})
        facts = {"started": datetime.now(UTC).isoformat(), "checks": 0, "ready": False}
        await ctx.request_info(Card("canary", plan, facts), str)

    @response_handler
    async def decide(self, card: Card, decision: str, ctx: WorkflowContext[Plan, str]) -> None:
        plan, checks = card.plan, card.facts["checks"] + 1
        if decision not in (CHECK, FORWARD[card.step]):
            return await self.undo(plan, ctx, "rolled back from canary")
        health = await self.platform.health(plan.slot)
        if not health.ok:
            return await self.undo(plan, ctx, f"canary failed: {health.failed} failed, p95 {health.p95_ms:.0f} ms")
        if decision == CHECK or not card.facts["ready"]:
            elapsed = round(hours_since(card.facts["started"]) * 60, 1)
            done = checks >= self.checks and elapsed >= self.minutes
            facts = card.facts | asdict(health) | {"checks": checks, "elapsed": elapsed, "ready": done}
            return await ctx.request_info(Card("canary", plan, facts), str)
        await self.go_live(plan, ctx)


class Window(Step):
    @handler
    async def start(self, plan: Plan, ctx: WorkflowContext[Never, str]) -> None:
        await ctx.request_info(Card("window", plan, {"rollback_to": plan.champion}), str)

    @response_handler
    async def decide(self, card: Card, decision: str, ctx: WorkflowContext[Never, str]) -> None:
        if decision != FORWARD[card.step]:
            await self.undo(card.plan, ctx, "rolled back in the window")
            return
        await self.platform.delete(card.plan.live)
        await ctx.yield_output(f"Model {card.plan.challenger} serves 100 %; model {card.plan.champion} was removed.")


def build(platform: Platform, storage: CheckpointStorage, checks: int, minutes: float) -> Workflow:
    compare, shadow, canary, window = (
        Compare(platform),
        Shadow(platform),
        Canary(platform, checks, minutes),
        Window(platform),
    )
    builder = WorkflowBuilder(MAX_SUPERSTEPS, NAME, start_executor=compare, checkpoint_storage=storage)
    return builder.add_edge(compare, shadow).add_edge(shadow, canary).add_edge(canary, window).build()


def status(result: WorkflowRunResult) -> Status:
    outputs, requests = result.get_outputs(), result.get_request_info_events()
    return Status(outputs[-1] if outputs else None, requests[0].data if requests else None)


def pending(head: WorkflowCheckpoint | None) -> Card | None:
    card: Card | None = next((e.data for e in (head.pending_request_info_events if head else {}).values()), None)
    return card


class Promotions:
    def __init__(
        self, platform: Platform, storage: CheckpointStorage, lease: Lease, checks: int = 15, minutes: float = 15
    ) -> None:
        self.platform, self.storage, self.lease = platform, storage, lease
        self.workflow = partial(build, platform, storage, checks, minutes)

    async def run(self, *start: str, **resume: Any) -> Status:
        try:
            return status(await self.workflow().run(*start, **resume))
        except NotReadyError as waiting:
            return Status(str(waiting), None)

    async def head(self) -> WorkflowCheckpoint | None:
        checkpoints = await self.storage.list_checkpoints(workflow_name=NAME)
        followed = {c.previous_checkpoint_id for c in checkpoints}
        unfinished = [c for c in checkpoints if c.pending_request_info_events or any(c.messages.values())]
        return next((c for c in unfinished if c.checkpoint_id not in followed), None)

    async def card(self) -> Card | None:
        return pending(await self.head())

    async def advance(self, head: WorkflowCheckpoint, decision: str | None) -> Status:
        if not head.pending_request_info_events:
            return await self.run(checkpoint_id=head.checkpoint_id)
        if decision is None:
            return Status(None, pending(head))
        responses = {next(iter(head.pending_request_info_events)): decision}
        return await self.run(checkpoint_id=head.checkpoint_id, responses=responses)

    async def start(self, version: str, approver: str = "") -> Status:
        async with self.lease.hold() as held:
            if held is None:
                return BUSY
            if await self.head():
                return Status("Another promotion is in progress.", None)
            event("approval_given", approver=approver, step="start", model=version, decision="approve")
            return await self.run(version)

    async def answer(self, decision: str, approver: str = "") -> Status:
        async with self.lease.hold() as held:
            if held is None:
                return BUSY
            head = await self.head()
            if not head or not (card := pending(head)):
                return Status("No promotion is waiting for a decision.", None)
            event("approval_given", approver=approver, step=card.step, model=card.plan.challenger, decision=decision)
            return await self.advance(head, decision)

    async def resume(self) -> Status:
        async with self.lease.hold() as held:
            if held is None:
                return BUSY
            head = await self.head()
            return await self.advance(head, None) if head else Status("No promotion is in progress.", None)

    async def tick(self) -> Status:
        async with self.lease.hold() as held:
            if held is None:
                return BUSY
            for run in await self.platform.runs(held.get("reported", "")):
                event("retrain_completed", pipeline_job=run.job, duration_minutes=run.minutes, model=run.version)
                event("model_evaluated", pipeline_job=run.job, recall_7d=run.recall_7d, precision_7d=run.precision_7d)
                held["reported"] = max(held.get("reported", ""), run.ended)
            head = await self.head()
            card = pending(head)
            if head and (card is None or (card.step == "canary" and not card.facts["ready"])):
                return await self.advance(head, CHECK)
            return Status(None, card)
