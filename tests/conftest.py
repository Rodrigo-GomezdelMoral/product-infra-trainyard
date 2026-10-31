import os
from collections.abc import Callable
from datetime import date
from typing import Any

import pandas as pd
import pytest
from agent_framework import SupportsChatGetResponse

from app.domain.simulator import Feed, simulate
from ml.features import training_rows
from tests.doubles import FakePlatform, Reply, Scripted

START = date(2026, 1, 1)


@pytest.fixture(scope="session")
def feed() -> Feed:
    return simulate(START, 90)


@pytest.fixture(scope="session")
def rows(feed: Feed) -> pd.DataFrame:
    return training_rows(feed.telemetry, feed.failures)


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
