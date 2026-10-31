import asyncio
from collections.abc import Callable
from pathlib import Path

import pytest
from agent_framework import CheckpointStorage, FileCheckpointStorage, InMemoryCheckpointStorage

from app.domain.simulator import Feed
from app.platform import Endpoint, Health, Model
from app.promotion import Promotions, Status, ready
from tests.doubles import FakePlatform

BACK = Endpoint({"blue": "2"}, {"blue": 100})


def steps(platform: FakePlatform, storage: Callable[[], CheckpointStorage], *actions: str) -> list[str]:
    async def act(action: str) -> Status:
        promotions, (verb, _, version) = Promotions(platform, storage(), checks=2, interval=0), action.partition(" ")
        if verb == "start":
            return await promotions.start(version)
        return await (promotions.resume() if verb == "resume" else promotions.answer(action))

    async def run() -> list[Status]:
        return [await act(action) for action in actions]

    return [s.card.step if s.card else str(s.outcome) for s in asyncio.run(run())]


def test_workflow_resumes_from_checkpoint(platform: FakePlatform, tmp_path: Path) -> None:
    def storage() -> CheckpointStorage:
        return FileCheckpointStorage(tmp_path)

    platform.canary = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        steps(platform, storage, "start 3", "approve")
    platform.canary = platform.healthy
    done = steps(platform, storage, "start 3", "resume", "promote", "close")
    assert done == [
        "Another promotion is in progress.",
        "canary",
        "window",
        "Model 3 serves 100 %; model 2 was removed.",
    ]
    assert platform.calls[-3:] == ["route {'green': 100, 'blue': 0} {}", "watch green", "delete blue"]
    assert platform.state == Endpoint({"green": "3"}, {"green": 100})


def test_shadow_step(platform: FakePlatform) -> None:
    platform.healthy, promotions = Health(57, 0, 170.0, 9.0, 0.95), Promotions(platform, InMemoryCheckpointStorage())

    async def run() -> list[Status]:
        return [*await asyncio.gather(promotions.start("3"), promotions.start("3")), await promotions.answer("approve")]

    shadow, busy, again = asyncio.run(run())
    pending = asyncio.run(Promotions(platform, promotions.storage).resume())
    facts = shadow.card.facts if shadow.card else {}
    assert (
        facts["offline"]["champion_recall"] == 0.84 and facts["challenger"]["agreement"] == 0.95 and not facts["ready"]
    )
    assert busy.outcome and busy.outcome.startswith("A promotion step is running") and not ready(Health(0, 0, 0, 30))
    assert [s.card and s.card.step for s in (again, pending)] == ["shadow", "shadow"]
    assert platform.calls == ["deploy green 3", "route {'blue': 100, 'green': 0} {'green': 20}"]


def test_canary_health_rollback(platform: FakePlatform) -> None:
    storage, platform.canary = InMemoryCheckpointStorage(), Health(120, 3, 450.0, 2.0)
    assert steps(platform, lambda: storage, "start 3", "approve")[1] == (
        "Model 3 removed (canary failed: 3 failed, p95 450 ms); model 2 serves 100 %."
    )
    rollback = [
        "route {'blue': 90, 'green': 10} {}",
        "route {'blue': 100, 'green': 0} {}",
        "watch blue",
        "delete green",
    ]
    assert platform.calls[-4:] == rollback and platform.state == BACK


def test_first_model_window_rollback_and_refusals(feed: Feed) -> None:
    first, storage = FakePlatform(feed, Endpoint({}, {})), InMemoryCheckpointStorage()
    assert steps(first, lambda: storage, "start 2", "approve") == ["first", "Model 2 serves 100 % from blue."]
    assert first.state == BACK and first.calls == ["deploy blue 2", "route {'blue': 100} {}", "watch blue"]
    platform = FakePlatform(feed)
    done = steps(platform, lambda: storage, "start 3", "approve", "promote", "rollback", "rollback")
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
