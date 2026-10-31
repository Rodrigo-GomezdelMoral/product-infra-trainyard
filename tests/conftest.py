import os
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path
from typing import Any

import mlflow
import pandas as pd
import pytest
from agent_framework import SupportsChatGetResponse

from app.domain.simulator import Feed, simulate
from ml.features import training_rows
from ml.steps import fit, save, split
from tests.doubles import FakePlatform, Reply, Scripted

START, LIMITS = date(2026, 1, 1), {"min_recall": 0.8, "min_precision": 0.6, "min_series_recall": 0.7}
LIMITS |= {"max_recall_loss": 0.02}


@pytest.fixture(scope="session")
def feed() -> Feed:
    return simulate(START, 90)


@pytest.fixture(scope="session")
def rows(feed: Feed) -> pd.DataFrame:
    return training_rows(feed.telemetry, feed.failures)


@pytest.fixture(scope="session", autouse=True)
def mlruns(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("MLFLOW_TRACKING_URI", tmp_path_factory.mktemp("mlruns").as_uri())
        yield


@pytest.fixture(scope="session")
def splits(rows: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return split(rows, 14, 14)


@pytest.fixture(scope="session")
def model(splits: dict[str, pd.DataFrame], tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("champion") / "model"
    save(fit(splits["train"], splits["validation"], 42, 6, 0.6)[0], splits["validation"], path)
    return path


@pytest.fixture
def tracking(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = (tmp_path / "mlruns").as_uri()
    monkeypatch.setenv("MLFLOW_TRACKING_URI", store)
    mlflow.set_tracking_uri(store)


@pytest.fixture
def platform(feed: Feed) -> FakePlatform:
    return FakePlatform(feed)


@pytest.fixture
def chat() -> Callable[..., SupportsChatGetResponse[Any]]:
    if not os.environ.get("FOUNDRY_PROJECT_ENDPOINT"):
        return Scripted
    from agent_framework.foundry import FoundryChatClient
    from azure.identity.aio import AzureCliCredential

    class Live(FoundryChatClient):
        async def __aenter__(self) -> "Live":
            return self

        async def __aexit__(self, *exc: object) -> None:
            await self.client.close()
            await credential.close()

    credential = AzureCliCredential()

    def live(*script: Reply) -> SupportsChatGetResponse[Any]:
        return Live(credential=credential)

    return live
