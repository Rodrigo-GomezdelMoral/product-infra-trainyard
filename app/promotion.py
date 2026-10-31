"""REQ-03, REQ-05: the model promotion as a checkpointed workflow; each traffic change waits for the owner."""

import asyncio
from dataclasses import asdict, dataclass
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

from app.platform import Health, Platform

NAME, SLOTS = "promotion", ("blue", "green")
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


class Step(Executor):
    def __init__(self, platform: Platform) -> None:
        super().__init__(id=type(self).__name__.lower())
        self.platform = platform

    async def go_live(self, plan: Plan, ctx: WorkflowContext[Plan, str]) -> None:
        await self.platform.route({plan.slot: 100} | ({plan.live: 0} if plan.live else {}), {})
        await self.platform.watch(plan.slot)
        if plan.live:
            await ctx.send_message(plan)
        else:
            await ctx.yield_output(f"Model {plan.challenger} serves 100 % from {plan.slot}.")

    async def undo(self, plan: Plan, ctx: WorkflowContext[Any, str], why: str) -> None:
        await self.platform.route({plan.live: 100, plan.slot: 0}, {})
        await self.platform.watch(plan.live)
        await self.platform.delete(plan.slot)
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
        await self.platform.deploy(card.plan.slot, card.plan.challenger)
        await self.go_live(card.plan, ctx)


class Shadow(Step):
    @handler
    async def start(self, plan: Plan, ctx: WorkflowContext[Plan, str]) -> None:
        await self.platform.deploy(plan.slot, plan.challenger)
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
            await self.undo(card.plan, ctx, "stopped in shadow")
        elif ready(await self.platform.health(card.plan.slot)):
            await ctx.send_message(card.plan)
        else:
            await self.ask(card.plan, ctx)


class Canary(Step):
    def __init__(self, platform: Platform, checks: int, interval: float) -> None:
        super().__init__(platform)
        self.checks, self.interval = max(checks, 1), interval

    @handler
    async def start(self, plan: Plan, ctx: WorkflowContext[Plan, str]) -> None:
        await self.platform.route({plan.live: 100 - CANARY, plan.slot: CANARY}, {})
        for _ in range(self.checks):
            await asyncio.sleep(self.interval)
            health = await self.platform.health(plan.slot)
            if not health.ok:
                await self.undo(plan, ctx, f"canary failed: {health.failed} failed, p95 {health.p95_ms:.0f} ms")
                return
        await ctx.request_info(Card("canary", plan, asdict(health)), str)

    @response_handler
    async def decide(self, card: Card, decision: str, ctx: WorkflowContext[Plan, str]) -> None:
        if decision == FORWARD[card.step]:
            await self.go_live(card.plan, ctx)
        else:
            await self.undo(card.plan, ctx, "rolled back from canary")


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


def build(platform: Platform, storage: CheckpointStorage, checks: int, interval: float) -> Workflow:
    compare, shadow, canary, window = (
        Compare(platform),
        Shadow(platform),
        Canary(platform, checks, interval),
        Window(platform),
    )
    builder = WorkflowBuilder(MAX_SUPERSTEPS, NAME, start_executor=compare, checkpoint_storage=storage)
    return builder.add_edge(compare, shadow).add_edge(shadow, canary).add_edge(canary, window).build()


def status(result: WorkflowRunResult) -> Status:
    outputs, requests = result.get_outputs(), result.get_request_info_events()
    return Status(outputs[-1] if outputs else None, requests[0].data if requests else None)


class Promotions:
    def __init__(self, platform: Platform, storage: CheckpointStorage, checks: int = 15, interval: float = 60) -> None:
        self.storage, self.workflow = storage, partial(build, platform, storage, checks, interval)
        self.lock = asyncio.Lock()

    async def head(self) -> WorkflowCheckpoint | None:
        checkpoints = await self.storage.list_checkpoints(workflow_name=NAME)
        followed = {c.previous_checkpoint_id for c in checkpoints}
        unfinished = [c for c in checkpoints if c.pending_request_info_events or any(c.messages.values())]
        return next((c for c in unfinished if c.checkpoint_id not in followed), None)

    async def start(self, version: str) -> Status:
        if self.lock.locked():
            return BUSY
        async with self.lock:
            if await self.head():
                return Status("Another promotion is in progress.", None)
            return status(await self.workflow().run(version))

    async def answer(self, decision: str) -> Status:
        if self.lock.locked():
            return BUSY
        async with self.lock:
            head = await self.head()
            if not head or not head.pending_request_info_events:
                return Status("No promotion is waiting for a decision.", None)
            responses = {next(iter(head.pending_request_info_events)): decision}
            return status(await self.workflow().run(checkpoint_id=head.checkpoint_id, responses=responses))

    async def resume(self) -> Status:
        if self.lock.locked():
            return BUSY
        async with self.lock:
            head = await self.head()
            if not head:
                return Status("No promotion is in progress.", None)
            if head.pending_request_info_events:
                return Status(None, next(iter(head.pending_request_info_events.values())).data)
            return status(await self.workflow().run(checkpoint_id=head.checkpoint_id))
