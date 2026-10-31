from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import mlflow
import pandas as pd
import pytest
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter, SimpleLogRecordProcessor

from app.domain.simulator import Feed, simulate
from app.telemetry import LOGGER
from eval.evaluators import THRESHOLDS
from ml.features import training_rows
from ml.steps import fit, save, split
from tests.doubles import START, FakePlatform

LIMITS, EVENT = THRESHOLDS["gate"], "microsoft.custom_event.name"


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
def events() -> Iterator[Callable[[], list[tuple[str, dict[str, Any]]]]]:
    exporter, provider = InMemoryLogRecordExporter(), LoggerProvider()
    provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
    LOGGER.addHandler(handler := LoggingHandler(logger_provider=provider))
    yield lambda: [
        (str(a.pop(EVENT)), a) for a in (dict(r.log_record.attributes or {}) for r in exporter.get_finished_logs())
    ]
    LOGGER.removeHandler(handler)
