"""The seam to Azure Machine Learning: what the agent and the promotion workflow need from it."""

from dataclasses import dataclass, field
from typing import Protocol

import pandas as pd

SLO_P95_MS, SLO_FAILED = 400.0, 0.003


class NotReadyError(Exception):
    """Azure is still applying a change; the promotion timer runs the step again a minute later (ADR-009)."""


@dataclass(frozen=True)
class Model:
    version: str
    metrics: dict[str, float]
    tags: dict[str, str]


@dataclass(frozen=True)
class Scores:
    frame: pd.DataFrame
    model: str
    threshold: float


@dataclass(frozen=True)
class Run:
    job: str
    ended: str
    minutes: float
    version: str
    recall_7d: float
    precision_7d: float


@dataclass(frozen=True)
class Health:
    requests: int
    failed: int
    p95_ms: float
    minutes: float
    agreement: float | None = None

    @property
    def ok(self) -> bool:
        return self.failed <= SLO_FAILED * self.requests and self.p95_ms < SLO_P95_MS


@dataclass(frozen=True)
class Endpoint:
    models: dict[str, str]
    live: dict[str, int]
    mirror: dict[str, int] = field(default_factory=dict)

    @property
    def champion(self) -> str | None:
        return next((slot for slot, share in self.live.items() if share == 100), None)


class Platform(Protocol):
    async def week(self) -> pd.DataFrame: ...

    async def score(self, rows: pd.DataFrame) -> Scores: ...

    async def models(self) -> list[Model]: ...

    async def endpoint(self) -> Endpoint: ...

    async def deploy(self, slot: str, version: str) -> None: ...

    async def route(self, live: dict[str, int], mirror: dict[str, int]) -> None: ...

    async def health(self, slot: str) -> Health: ...

    async def delete(self, slot: str) -> None: ...

    async def watch(self, slot: str) -> None: ...

    async def retrain(self) -> dict[str, str]: ...

    async def monitor(self) -> dict[str, str]: ...

    async def runs(self, after: str) -> list[Run]: ...
