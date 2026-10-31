import asyncio
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import replace
from datetime import date
from secrets import token_hex
from typing import Any, cast

import numpy as np
import pandas as pd
from agent_framework import (
    BaseChatClient,
    ChatResponse,
    ChatResponseUpdate,
    CheckpointStorage,
    Content,
    FunctionInvocationLayer,
    InMemoryCheckpointStorage,
    Message,
    ResponseStream,
)
from azure.core.exceptions import ServiceRequestError
from azure.cosmos.aio import ContainerProxy
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)

from app.domain.simulator import Feed
from app.platform import Endpoint, Health, Model, Run, Scores
from app.promotion import Promotions
from app.store import Lease
from ml.features import FEATURES, features

START, WEEK, THRESHOLD = date(2026, 1, 1), pd.Timestamp("2026-01-26"), 0.44
WEIGHTS = pd.Series({"duty_parked": 0.5, "below_cut_in": 0.4, "duty_trend": 0.3, "oil_temperature_max": 0.2})
LINEAGE = {"data_asset": "fleet-feed", "gate": "passed"}
Reply = Message | Callable[[Sequence[Message]], Message]


class FakePlatform:
    def __init__(self, feed: Feed, endpoint: Endpoint | None = None) -> None:
        self.rows = features(feed.telemetry, feed.failures, WEEK)
        self.state = endpoint or Endpoint({"blue": "2"}, {"blue": 100})
        champion = {"recall": 0.84, "precision": 0.63}
        self.registered = [
            Model(
                "2", champion, LINEAGE | {"data_version": "4", "pipeline_job": "teal_kettle_7", "git_sha": "9d2c4ab"}
            ),
            Model(
                "3",
                {"recall": 0.86, "precision": 0.66} | {f"champion_{name}": value for name, value in champion.items()},
                LINEAGE
                | {"data_version": "5", "pipeline_job": "brave_engine_3", "git_sha": "4f1e0c2", "champion": "2"},
            ),
        ]
        self.healthy = Health(240, 0, 182.0, 31.0, 0.96)
        self.canary: Health | BaseException = self.healthy
        self.calls: list[str] = []
        self.completed = [Run("quiet_signal_8", "2026-01-26T05:10:00+00:00", 84.0, "3", 0.86, 0.66)]
        self.breached_at = "2026-01-25T03:40:00+00:00"

    async def week(self) -> pd.DataFrame:
        return self.rows

    async def score(self, rows: pd.DataFrame) -> Scores:
        signals = rows[WEIGHTS.index]
        pushed = ((signals - signals.median()) / signals.std()).clip(-3, 3) * WEIGHTS
        frame = pd.DataFrame(0.0, index=rows.index, columns=list(FEATURES))
        frame[list(WEIGHTS.index)] = pushed
        probability = 1 / (1 + np.exp(1 - pushed.sum(axis=1)))
        return Scores(
            frame.assign(unit=rows["unit"], probability=probability),
            self.state.models[self.state.champion or "blue"],
            THRESHOLD,
        )

    async def models(self) -> list[Model]:
        return self.registered

    async def endpoint(self) -> Endpoint:
        return self.state

    async def deploy(self, slot: str, version: str) -> None:
        self.state = replace(self.state, models=self.state.models | {slot: version})
        self.calls.append(f"deploy {slot} {version}")

    async def route(self, live: dict[str, int], mirror: dict[str, int]) -> None:
        self.state = replace(self.state, live=live, mirror=mirror)
        self.calls.append(f"route {live} {mirror}")

    async def health(self, slot: str) -> Health:
        if self.state.live.get(slot) != 10:
            return self.healthy
        if isinstance(self.canary, BaseException):
            raise self.canary
        return self.canary

    async def delete(self, slot: str) -> None:
        drop = {name: {k: v for k, v in getattr(self.state, name).items() if k != slot} for name in ("models", "live")}
        self.state = replace(self.state, **drop)
        self.calls.append(f"delete {slot}")

    async def watch(self, slot: str) -> None:
        self.calls.append(f"watch {slot}")

    async def retrain(self) -> dict[str, str]:
        self.calls.append("retrain")
        return {"pipeline_job": "quiet_signal_8", "data_asset": "fleet-feed", "data_version": "5", "status": "Running"}

    async def monitor(self) -> dict[str, str]:
        signals = {
            "run_date": "2026-01-26",
            "signals": "data drift, prediction drift, data quality",
            "breached": "none",
        }
        return signals | {"breached_at": self.breached_at}

    async def runs(self, after: str) -> list[Run]:
        return [run for run in self.completed if run.ended > after]


class FakeContainer:
    def __init__(self, key: str, yields: bool = False) -> None:
        self.key, self.yields, self.docs, self.down = key, yields, dict[tuple[str, str], dict[str, Any]](), False

    async def ready(self, key: tuple[str, str], exists: bool | None = None) -> None:
        if self.yields:
            await asyncio.sleep(0)
        if self.down:
            raise ServiceRequestError("The store is unreachable.")
        if exists is True and key not in self.docs:
            raise CosmosResourceNotFoundError(404, "Not found.")
        if exists is False and key in self.docs:
            raise CosmosResourceExistsError(409, "Exists.")

    def put(self, body: dict[str, Any]) -> dict[str, Any]:
        self.docs[(body[self.key], body["id"])] = body | {"_etag": token_hex(4)}
        return dict(self.docs[(body[self.key], body["id"])])

    async def read_item(self, item: str, partition_key: str) -> dict[str, Any]:
        await self.ready((partition_key, item), True)
        return dict(self.docs[(partition_key, item)])

    async def create_item(self, body: dict[str, Any]) -> dict[str, Any]:
        await self.ready((body[self.key], body["id"]), False)
        return self.put(body)

    async def replace_item(self, item: str, body: dict[str, Any], etag: str, **kwargs: Any) -> dict[str, Any]:
        await self.ready((body[self.key], item), True)
        if self.docs[(body[self.key], item)]["_etag"] != etag:
            raise CosmosAccessConditionFailedError(412, "Changed.")
        return self.put(body)

    async def upsert_item(self, body: dict[str, Any]) -> dict[str, Any]:
        await self.ready((body[self.key], body["id"]))
        return self.put(body)

    async def delete_item(self, item: str, partition_key: str) -> None:
        await self.ready((partition_key, item), True)
        del self.docs[(partition_key, item)]

    async def query_items(self, query: str, partition_key: str) -> AsyncIterator[dict[str, Any]]:
        await self.ready(("", ""))
        for doc in [doc for (key, _), doc in self.docs.items() if key == partition_key]:
            yield doc


def promotions(platform: FakePlatform, storage: CheckpointStorage | None = None, leases: Any = None) -> Promotions:
    lease = Lease(cast(ContainerProxy, leases or FakeContainer("workflow_name")))
    return Promotions(platform, storage or InMemoryCheckpointStorage(), lease, checks=2, minutes=0)


def say(text: str) -> Message:
    return Message("assistant", [text])


def call(name: str, **arguments: str) -> Message:
    return Message("assistant", [Content.from_function_call(name, name, arguments=arguments)])


def results(messages: Sequence[Message]) -> str:
    return "\n".join(str(c.result) for m in messages for c in m.contents if c.type == "function_result")


def echo(messages: Sequence[Message]) -> Message:
    return say(results(messages))


class Scripted(FunctionInvocationLayer[Any], BaseChatClient[Any]):
    def __init__(self, *script: Reply) -> None:
        super().__init__()
        self.script = list(script)

    async def reply(self, messages: Sequence[Message]) -> ChatResponse[Any]:
        step = self.script.pop(0)
        return ChatResponse(messages=[step(messages) if callable(step) else step])

    async def updates(self, messages: Sequence[Message]) -> AsyncIterator[ChatResponseUpdate]:
        yield ChatResponseUpdate(contents=(await self.reply(messages)).messages[0].contents, role="assistant")

    def _inner_get_response(
        self, *, messages: Sequence[Message], stream: bool, options: Mapping[str, Any], **kwargs: Any
    ) -> Any:
        return (
            ResponseStream(self.updates(messages), finalizer=ChatResponse.from_updates)
            if stream
            else self.reply(messages)
        )
