from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from agent_framework import BaseChatClient, ChatResponse, Content, FunctionInvocationLayer, Message

from app.domain.simulator import Feed
from app.platform import Endpoint, Health, Model, Scores
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
        return {"run_date": "2026-01-26", "signals": "data drift, prediction drift, data quality", "breached": "none"}


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

    def _inner_get_response(
        self, *, messages: Sequence[Message], stream: bool, options: Mapping[str, Any], **kwargs: Any
    ) -> Any:
        return self.reply(messages)
