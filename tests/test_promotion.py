import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from agent_framework import CheckpointStorage, FileCheckpointStorage, InMemoryCheckpointStorage

from app.domain.simulator import Feed
from app.platform import Endpoint, Health, Model
from app.promotion import BUSY, Status, ready
from tests.doubles import FakeContainer, FakePlatform, promotions

BACK, SERVED = Endpoint({"blue": "2"}, {"blue": 100}), "Model 3 serves 100 %; model 2 was removed."
Events = Callable[[], list[tuple[str, dict[str, Any]]]]


def steps(platform: FakePlatform, storage: Callable[[], CheckpointStorage], *actions: str) -> list[str]:
    leases = FakeContainer("workflow_name")

    async def act(action: str) -> Status:
        replica, (verb, _, version) = promotions(platform, storage(), leases), action.partition(" ")
        if verb in ("start", "tick", "resume"):
            return await (replica.start(version) if verb == "start" else getattr(replica, verb)())
        return await replica.answer(action)

    async def run() -> list[Status]:
        return [await act(action) for action in actions]

    return [s.card.step if s.card else str(s.outcome) for s in asyncio.run(run())]


def test_workflow_resumes_from_checkpoint(platform: FakePlatform, tmp_path: Path, monkeypatch: Any) -> None:
    def storage() -> CheckpointStorage:
        return FileCheckpointStorage(tmp_path)

    async def cut(live: dict[str, int], mirror: dict[str, int]) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(platform, "route", cut)
    with pytest.raises(asyncio.CancelledError):
        steps(platform, storage, "start 3")
    monkeypatch.undo()
    platform.canary = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        steps(platform, storage, "resume", "approve", "tick")
    platform.canary = platform.healthy
    done = steps(platform, storage, "start 3", "resume", "promote", "tick", "tick", "promote", "close")
    assert done == ["Another promotion is in progress.", "canary", "canary", "canary", "canary", "window", SERVED]
    assert platform.calls[-3:] == ["route {'green': 100, 'blue': 0} {}", "watch green", "delete blue"]
    assert platform.state == Endpoint({"green": "3"}, {"green": 100})


def test_shadow_step(platform: FakePlatform) -> None:
    platform.healthy, replica = Health(57, 0, 170.0, 9.0, 0.95), promotions(platform)

    async def run() -> list[Status]:
        return [*await asyncio.gather(replica.start("3"), replica.start("3")), await replica.answer("approve")]

    shadow, busy, again = asyncio.run(run())
    pending = asyncio.run(promotions(platform, replica.storage).resume())
    facts = shadow.card.facts if shadow.card else {}
    assert (
        facts["offline"]["champion_recall"] == 0.84 and facts["challenger"]["agreement"] == 0.95 and not facts["ready"]
    )
    assert busy == BUSY and not ready(Health(0, 0, 0, 30))
    assert [s.card and s.card.step for s in (again, pending)] == ["shadow", "shadow"]
    assert platform.calls == ["deploy green 3", "route {'blue': 100, 'green': 0} {'green': 20}"]


def test_canary_health_rollback(platform: FakePlatform) -> None:
    storage = InMemoryCheckpointStorage()
    assert steps(platform, lambda: storage, "start 3", "approve", "rollback")[-1] == (
        "Model 3 removed (rolled back from canary); model 2 serves 100 %."
    )
    platform.canary = Health(120, 3, 450.0, 2.0)
    assert steps(platform, lambda: storage, "start 3", "approve", "tick")[-1] == (
        "Model 3 removed (canary failed: 3 failed, p95 450 ms); model 2 serves 100 %."
    )
    rollback = [
        "route {'blue': 90, 'green': 10} {}",
        "route {'blue': 100, 'green': 0} {}",
        "watch blue",
        "delete green",
    ]
    assert platform.calls[-4:] == rollback and platform.state == BACK


def test_one_writer_across_replicas(platform: FakePlatform, tmp_path: Path) -> None:
    leases = FakeContainer("workflow_name", yields=True)
    first, second = (promotions(platform, FileCheckpointStorage(tmp_path), leases) for _ in range(2))

    async def run() -> list[Status]:
        opened = await asyncio.gather(first.start("3"), second.start("3"))
        raced = await asyncio.gather(first.answer("approve"), second.answer("rollback"))
        done = [await first.tick(), await first.tick(), await first.answer("promote"), await first.answer("close")]
        return [*opened, *raced, *done, await second.answer("rollback")]

    outcomes = [s.card.step if s.card else s.outcome for s in asyncio.run(run())]
    waiting = "No promotion is waiting for a decision."
    assert outcomes == ["shadow", BUSY.outcome, "canary", BUSY.outcome, "canary", "canary", "window", SERVED, waiting]
    assert platform.state == Endpoint({"green": "3"}, {"green": 100}) and "delete green" not in platform.calls


def test_first_model_window_rollback_and_refusals(feed: Feed, events: Events) -> None:
    first, storage = FakePlatform(feed, Endpoint({}, {})), InMemoryCheckpointStorage()
    assert steps(first, lambda: storage, "start 2", "approve") == ["first", "Model 2 serves 100 % from blue."]
    assert first.state == BACK and first.calls == ["deploy blue 2", "route {'blue': 100} {}", "watch blue"]
    platform = FakePlatform(feed)
    done = steps(platform, lambda: storage, "start 3", "approve", "tick", "tick", "promote", "rollback", "rollback")
    assert done[-2:] == [
        "Model 3 removed (rolled back in the window); model 2 serves 100 %.",
        "No promotion is waiting for a decision.",
    ]
    assert platform.state == BACK
    platform.registered += [
        Model("4", {"recall": 0.8, "champion_recall": 0.84}, {"champion": "2"}),
        Model("5", {"recall": 0.9}, {"champion": "2"}),
    ]
    assert steps(platform, lambda: storage, "start 4", "start 5", "resume") == [
        "Model 4 lost to model 2 on the same holdout.",
        "Model 5 was not compared with model 2: retrain first.",
        "No promotion is in progress.",
    ]
    platform.state = Endpoint({"blue": "2", "green": "3"}, {"blue": 100})
    assert steps(platform, lambda: storage, "start 3") == [
        "Model 3 cannot start: it is not registered or both slots are busy."
    ]
    seen = [name for name, _ in events() if name != "approval_given"]
    assert seen == ["model_promoted", "retrain_completed", "model_evaluated", "model_promoted", "model_rolled_back"]
    approvals = [(a["step"], a["model"], a["decision"]) for name, a in events() if name == "approval_given"]
    assert approvals[2:6] == [
        ("start", "3", "approve"),
        ("shadow", "3", "approve"),
        ("canary", "3", "promote"),
        ("window", "3", "rollback"),
    ]
    promoted = [a for name, a in events() if name == "model_promoted"]
    assert "drift_to_promotion_hours" in promoted[1] and promoted[1]["drift_to_promotion_hours"] > 0
